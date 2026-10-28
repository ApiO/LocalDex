#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Non-interactive, non-destructive archive extraction for SyntyLibrary.

The output_dir is read from the repository's config.yml/config.yaml. Archive
files are extracted beside their source archive. Unity packages are always
ignored. Existing identical files are kept; differing files are timestamped
before the new version is installed.
"""
from __future__ import annotations

import argparse
import bz2
import gzip
import hashlib
import lzma
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

try:
    import yaml
except ImportError:  # Friendly error when run outside the downloader venv.
    yaml = None

MAX_ARCHIVE_ENTRIES = 200_000
MAX_UNCOMPRESSED_BYTES = 200 * 1024**3
COPY_CHUNK = 1024 * 1024

# Longest suffixes first, so .tar.gz is not treated as a plain .gz file.
ARCHIVE_SUFFIXES = (
    ".unitypackage", ".tar.bz2", ".tar.gz", ".tar.xz", ".tbz2", ".tgz",
    ".txz", ".tar", ".zip", ".bz2", ".gz", ".xz", ".7z", ".rar",
)
TAR_SUFFIXES = {".tar", ".tar.bz2", ".tar.gz", ".tar.xz", ".tbz2", ".tgz", ".txz"}
PLAIN_COMPRESSED_SUFFIXES = {".bz2", ".gz", ".xz"}
IGNORED_DIRECTORY_NAMES = {
    ".git", ".venv", "__pycache__", ".localdex", ".synty-partials",
    ".synty_browser_profile", ".synty_browser_profile_linux",
}


class ExtractionError(RuntimeError):
    """An archive could not be safely extracted or merged."""


@dataclass
class ExtractionResult:
    extracted: int = 0
    replaced: int = 0
    skipped_identical: int = 0
    bytes_written: int = 0


def get_suffix(name: str) -> str:
    lowered = name.lower()
    return next((suffix for suffix in ARCHIVE_SUFFIXES if lowered.endswith(suffix)), "")


def archive_stem(path: Path, suffix: str | None = None) -> str:
    suffix = suffix or get_suffix(path.name)
    stem = path.name[:-len(suffix)] if suffix else path.stem
    stem = stem.rstrip(" .")
    return stem or f"{path.name}_extracted"


def destination_for(path: Path, suffix: str) -> tuple[Path, bool]:
    """Return (destination, is_single_file) for an archive."""
    if suffix in PLAIN_COMPRESSED_SUFFIXES and suffix not in TAR_SUFFIXES:
        return path.with_name(path.name[:-len(suffix)]), True
    return path.parent / archive_stem(path, suffix), False


def _safe_relative(name: str) -> Path:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ExtractionError("Archive contains an empty or invalid path.")
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if member.is_absolute() or any(part == ".." for part in member.parts):
        raise ExtractionError(f"Unsafe archive path rejected: {name[:180]}")
    if any(":" in part for part in member.parts):
        raise ExtractionError(f"Unsafe archive path rejected: {name[:180]}")
    parts = [part for part in member.parts if part not in ("", ".")]
    if not parts:
        raise ExtractionError(f"Archive contains an invalid path: {name[:180]}")
    return Path(*parts)


def _check_limits(entry_count: int, total_size: int) -> None:
    if entry_count > MAX_ARCHIVE_ENTRIES:
        raise ExtractionError(f"Archive has more than {MAX_ARCHIVE_ENTRIES:,} entries.")
    if total_size < 0 or total_size > MAX_UNCOMPRESSED_BYTES:
        raise ExtractionError("Archive exceeds the 200 GiB uncompressed size limit.")


def _copy_stream(stream: BinaryIO, target: Path, expected_size: int | None,
                 remaining_limit: int) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open("xb") as output:
        while True:
            chunk = stream.read(COPY_CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UNCOMPRESSED_BYTES or written > remaining_limit:
                raise ExtractionError("Archive data exceeds the uncompressed size limit.")
            if expected_size is not None and written > expected_size:
                raise ExtractionError("Archive entry is larger than its declared size.")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if expected_size is not None and written != expected_size:
        raise ExtractionError("Archive entry size does not match its directory record.")
    return written


def _check_unique_members(entries: Iterable[tuple[str, Path, bool, int]]) -> list[tuple[str, Path, bool, int]]:
    checked: list[tuple[str, Path, bool, int]] = []
    seen: dict[str, bool] = {}
    total_size = 0
    for name, relative, is_dir, size in entries:
        key = relative.as_posix().casefold()
        if key in seen:
            raise ExtractionError(f"Archive contains duplicate paths: {name[:180]}")
        seen[key] = is_dir
        if size < 0:
            raise ExtractionError(f"Archive contains an invalid size: {name[:180]}")
        if not is_dir:
            total_size += size
        checked.append((name, relative, is_dir, size))
    _check_limits(len(checked), total_size)
    # Reject a file that is also the parent directory of another member.
    for _, relative, is_dir, _ in checked:
        for parent in relative.parents:
            if parent == Path("."):
                continue
            parent_kind = seen.get(parent.as_posix().casefold())
            if parent_kind is False:
                raise ExtractionError(f"Archive path conflicts with a file: {parent.as_posix()}")
    return checked


def _extract_zip(source: Path, stage: Path) -> tuple[int, int]:
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        raw_entries = []
        for info in infos:
            relative = _safe_relative(info.filename.rstrip("/")) if not info.is_dir() or info.filename.rstrip("/") else None
            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            is_dir = info.is_dir() or file_type == stat.S_IFDIR
            if file_type == stat.S_IFLNK or file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ExtractionError(f"Links and special files are not allowed: {info.filename[:180]}")
            if relative is not None:
                raw_entries.append((info.filename, relative, is_dir, info.file_size if not is_dir else 0, info))
        checked = _check_unique_members((name, relative, is_dir, size) for name, relative, is_dir, size, _ in raw_entries)
        by_name = {name: info for name, _, _, _, info in raw_entries}
        total_written = 0
        file_count = 0
        for name, relative, is_dir, size in checked:
            target = stage / relative
            if is_dir:
                target.mkdir(parents=True, exist_ok=True)
                continue
            info = by_name[name]
            with archive.open(info, "r") as stream:
                written = _copy_stream(stream, target, size, MAX_UNCOMPRESSED_BYTES - total_written)
            total_written += written
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                target.chmod(mode)
            file_count += 1
        return file_count, total_written


def _extract_tar(source: Path, stage: Path) -> tuple[int, int]:
    with tarfile.open(source, mode="r:*") as archive:
        members = archive.getmembers()
        raw_entries = []
        for member in members:
            relative = _safe_relative(member.name.rstrip("/")) if not member.isdir() or member.name.rstrip("/") else None
            if member.isdir():
                is_dir = True
            elif member.isfile():
                is_dir = False
            else:
                raise ExtractionError(f"Links and special files are not allowed: {member.name[:180]}")
            if relative is not None:
                raw_entries.append((member.name, relative, is_dir, member.size if not is_dir else 0, member))
        checked = _check_unique_members((name, relative, is_dir, size) for name, relative, is_dir, size, _ in raw_entries)
        by_name = {name: member for name, _, _, _, member in raw_entries}
        total_written = 0
        file_count = 0
        for name, relative, is_dir, size in checked:
            target = stage / relative
            if is_dir:
                target.mkdir(parents=True, exist_ok=True)
                continue
            member = by_name[name]
            stream = archive.extractfile(member)
            if stream is None:
                raise ExtractionError(f"Could not read archive entry: {name[:180]}")
            with stream:
                written = _copy_stream(stream, target, size, MAX_UNCOMPRESSED_BYTES - total_written)
            total_written += written
            if member.mode & 0o777:
                target.chmod(member.mode & 0o777)
            file_count += 1
        return file_count, total_written


def _extract_plain_compressed(source: Path, stage: Path, suffix: str) -> tuple[int, int]:
    output_name = source.name[:-len(suffix)]
    relative = _safe_relative(output_name)
    target = stage / relative
    opener = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}[suffix]
    with opener(source, "rb") as stream:
        written = _copy_stream(stream, target, None, MAX_UNCOMPRESSED_BYTES)
    return 1, written


def _seven_zip_binary() -> str | None:
    return shutil.which("7zz") or shutil.which("7z")


def _extract_with_7z(source: Path, stage: Path) -> tuple[int, int]:
    binary = _seven_zip_binary()
    if not binary:
        raise ExtractionError("RAR/7z extraction requires the '7z' or '7zz' command; it was not found.")
    try:
        listing = subprocess.run(
            [binary, "l", "-slt", str(source)], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExtractionError(f"Could not inspect archive with 7-Zip: {exc}") from exc
    if listing.returncode != 0:
        detail = (listing.stderr or listing.stdout).strip()[-1000:]
        raise ExtractionError(f"7-Zip could not inspect archive: {detail or listing.returncode}")

    records: list[dict[str, str]] = []
    record: dict[str, str] = {}
    for line in listing.stdout.splitlines():
        if line.strip() == "----------":
            if record:
                records.append(record)
                record = {}
        elif " = " in line:
            key, value = line.split(" = ", 1)
            record[key.strip()] = value.strip()
    if record:
        records.append(record)

    entries = []
    archive_names = {str(source), str(source.resolve()), source.name}
    for item in records:
        name = item.get("Path", "")
        if not name or name in archive_names:
            continue
        relative = _safe_relative(name.rstrip("/\\"))
        attrs = item.get("Attributes", "")
        if re.search(r"(?:^|\s)l[rwxstST-]{9}(?:\s|$)", attrs):
            raise ExtractionError(f"Symbolic links are not allowed: {name[:180]}")
        is_dir = item.get("Folder", "").strip() == "+"
        try:
            size = int(item.get("Size", "0") or "0") if not is_dir else 0
        except ValueError as exc:
            raise ExtractionError(f"Invalid 7-Zip file size for {name[:180]}") from exc
        entries.append((name, relative, is_dir, size))
    checked = _check_unique_members(entries)
    if not checked:
        raise ExtractionError("7-Zip did not report any archive entries.")
    try:
        result = subprocess.run(
            [binary, "x", "-y", "-p-", f"-o{stage}", str(source)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=1800, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExtractionError(f"Could not extract archive with 7-Zip: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise ExtractionError(f"7-Zip extraction failed: {detail or result.returncode}")
    files, total = _inspect_stage(stage)
    return files, total


def _inspect_stage(stage: Path) -> tuple[int, int]:
    count = 0
    total = 0
    for current, dirs, files in os.walk(stage, followlinks=False):
        base = Path(current)
        for dirname in list(dirs):
            item = base / dirname
            if item.is_symlink() or not item.is_dir():
                raise ExtractionError(f"Links or special files are not allowed: {item.name}")
        for filename in files:
            item = base / filename
            if item.is_symlink() or not item.is_file():
                raise ExtractionError(f"Links or special files are not allowed: {item.name}")
            count += 1
            total += item.stat().st_size
            if count > MAX_ARCHIVE_ENTRIES or total > MAX_UNCOMPRESSED_BYTES:
                raise ExtractionError("Archive exceeds the entry count or uncompressed size limit.")
    return count, total


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(COPY_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _unique_backup_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = path.with_name(f"{path.stem}_{stamp}{path.suffix}")
    sequence = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{path.stem}_{stamp}_{sequence}{path.suffix}")
        sequence += 1
    return candidate


def _check_existing_path(root: Path, relative: Path, want_directory: bool) -> Path:
    target = root / relative
    current = root
    if current.is_symlink():
        raise ExtractionError(f"Destination root is a symbolic link: {current}")
    for part in relative.parts[:-1] if not want_directory else relative.parts:
        current = current / part
        if current.is_symlink():
            raise ExtractionError(f"Destination path contains a symbolic link: {current}")
        if current.exists() and not current.is_dir():
            raise ExtractionError(f"Destination directory conflicts with an existing file: {current}")
    if target.is_symlink():
        raise ExtractionError(f"Destination is a symbolic link: {target}")
    if target.exists():
        if want_directory and not target.is_dir():
            raise ExtractionError(f"A file already occupies the destination directory: {target}")
        if not want_directory and not target.is_file():
            raise ExtractionError(f"Destination is not a regular file: {target}")
    return target


def _merge_file(staged: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ExtractionError(f"Destination is a symbolic link: {target}")
    if target.exists():
        if not target.is_file():
            raise ExtractionError(f"Destination is not a regular file: {target}")
        if _hash_file(staged) == _hash_file(target):
            return "same"
        backup = _unique_backup_path(target)
        os.replace(target, backup)
        try:
            os.replace(staged, target)
        except Exception:
            if not target.exists() and backup.exists():
                os.replace(backup, target)
            raise
        return "replaced"
    os.replace(staged, target)
    return "extracted"


def _merge_directory(stage: Path, destination: Path) -> ExtractionResult:
    if destination.is_symlink():
        raise ExtractionError(f"Destination directory is a symbolic link: {destination}")
    if destination.exists() and not destination.is_dir():
        raise ExtractionError(f"A file already occupies the destination directory: {destination}")

    stage_dirs: list[Path] = []
    stage_files: list[Path] = []
    for current, dirs, files in os.walk(stage, followlinks=False):
        base = Path(current)
        for dirname in list(dirs):
            item = base / dirname
            if item.is_symlink() or not item.is_dir():
                raise ExtractionError(f"Links or special files are not allowed: {item}")
            stage_dirs.append(item.relative_to(stage))
        for filename in files:
            item = base / filename
            if item.is_symlink() or not item.is_file():
                raise ExtractionError(f"Links or special files are not allowed: {item}")
            stage_files.append(item.relative_to(stage))

    # Validate every existing path before changing any of the destination files.
    for relative in sorted(stage_dirs, key=lambda item: (len(item.parts), item.as_posix().casefold())):
        _check_existing_path(destination, relative, True)
    for relative in stage_files:
        _check_existing_path(destination, relative, False)

    destination.mkdir(parents=True, exist_ok=True)
    for relative in sorted(stage_dirs, key=lambda item: (len(item.parts), item.as_posix().casefold())):
        (destination / relative).mkdir(parents=True, exist_ok=True)

    result = ExtractionResult()
    for relative in sorted(stage_files, key=lambda item: item.as_posix().casefold()):
        staged = stage / relative
        target = destination / relative
        status = _merge_file(staged, target)
        if status == "same":
            result.skipped_identical += 1
        elif status == "replaced":
            result.replaced += 1
            result.bytes_written += target.stat().st_size
        else:
            result.extracted += 1
            result.bytes_written += target.stat().st_size
    return result


def _merge_single_file(stage: Path, target: Path, output_name: str) -> ExtractionResult:
    staged = stage / _safe_relative(output_name)
    if not staged.is_file() or staged.is_symlink():
        raise ExtractionError("Decompression did not produce the expected output file.")
    # Validate its existing parents and target without resolving/following symlinks.
    root = target.parent
    if root.is_symlink():
        raise ExtractionError(f"Destination directory is a symbolic link: {root}")
    for parent in (root, *root.parents):
        if parent == target.anchor:
            break
        if parent.is_symlink():
            raise ExtractionError(f"Destination path contains a symbolic link: {parent}")
    if target.is_symlink():
        raise ExtractionError(f"Destination is a symbolic link: {target}")
    if target.exists() and not target.is_file():
        raise ExtractionError(f"Destination is not a regular file: {target}")
    root.mkdir(parents=True, exist_ok=True)
    status = _merge_file(staged, target)
    result = ExtractionResult()
    if status == "same":
        result.skipped_identical = 1
    elif status == "replaced":
        result.replaced = 1
        result.bytes_written = target.stat().st_size
    else:
        result.extracted = 1
        result.bytes_written = target.stat().st_size
    return result


def extract_archive(source: Path, suffix: str) -> ExtractionResult:
    destination, single_file = destination_for(source, suffix)
    # Stage beside the source so moving completed files into place stays on the same filesystem.
    with tempfile.TemporaryDirectory(prefix=".extract-stage-", dir=source.parent) as temp_dir:
        stage = Path(temp_dir)
        if suffix == ".zip":
            _extract_zip(source, stage)
        elif suffix in TAR_SUFFIXES:
            _extract_tar(source, stage)
        elif suffix in PLAIN_COMPRESSED_SUFFIXES:
            _extract_plain_compressed(source, stage, suffix)
        elif suffix in {".7z", ".rar"}:
            _extract_with_7z(source, stage)
        else:
            raise ExtractionError(f"Unsupported archive format: {suffix or source.suffix}")
        if single_file:
            output_name = source.name[:-len(suffix)]
            return _merge_single_file(stage, destination, output_name)
        return _merge_directory(stage, destination)


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def discover_archives(root: Path) -> tuple[list[tuple[Path, str]], int]:
    all_archives: list[tuple[Path, str]] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(
            name for name in dirs
            if name not in IGNORED_DIRECTORY_NAMES
            and not name.startswith((".extract-stage-", ".localdex-extract-"))
            and not (base / name).is_symlink()
        )
        for filename in sorted(files, key=str.casefold):
            path = base / filename
            if path.is_symlink() or not path.is_file():
                continue
            suffix = get_suffix(filename)
            if suffix:
                all_archives.append((path, suffix))

    # Do not recursively re-process archives that are already inside another
    # archive's sibling extraction directory.
    extraction_dirs: set[Path] = set()
    for path, suffix in all_archives:
        if suffix == ".unitypackage":
            continue
        destination, single_file = destination_for(path, suffix)
        if not single_file:
            extraction_dirs.add(destination.resolve())

    candidates: list[tuple[Path, str]] = []
    ignored_unity = 0
    for path, suffix in all_archives:
        resolved = path.resolve()
        if any(_is_within(resolved, directory) for directory in extraction_dirs):
            continue
        if suffix == ".unitypackage":
            ignored_unity += 1
            continue
        candidates.append((path, suffix))
    candidates.sort(key=lambda item: item[0].relative_to(root).as_posix().casefold())
    return candidates, ignored_unity


def load_config(explicit_path: str | None, script_dir: Path, project_root: Path) -> tuple[Path, dict]:
    if yaml is None:
        raise ExtractionError(
            "PyYAML is required. Run this script through SyntyDownloader/.venv/bin/python "
            "or install it with: python3 -m pip install PyYAML"
        )
    if explicit_path:
        config_path = Path(explicit_path).expanduser()
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        config_path = config_path.resolve()
        if not config_path.is_file():
            raise ExtractionError(f"Configuration file not found: {config_path}")
    else:
        candidates = [
            project_root / "config.yml", project_root / "config.yaml",
            script_dir / "config.yml", script_dir / "config.yaml",
        ]
        config_path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if config_path is None:
            expected = " or ".join(str(path) for path in candidates)
            raise ExtractionError(f"No config.yml/config.yaml found. Checked: {expected}")
        config_path = config_path.resolve()
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ExtractionError(f"Could not read YAML configuration {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtractionError(f"Configuration must contain a YAML mapping: {config_path}")
    output_value = data.get("output_dir")
    if not isinstance(output_value, str) or not output_value.strip():
        raise ExtractionError(f"'output_dir' must be a non-empty path in {config_path}")
    output_dir = Path(output_value).expanduser()
    if not output_dir.is_absolute():
        output_dir = config_path.parent / output_dir
    return config_path, output_dir.resolve()


def make_logger(output_dir: Path, log_override: str | None) -> logging.Logger:
    logger = logging.getLogger("synty_archive_extractor")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    log_path = Path(log_override).expanduser() if log_override else output_dir / ".extract_archives.log"
    if not log_path.is_absolute():
        log_path = Path.cwd() / log_path
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.is_symlink():
            raise OSError("log path is a symbolic link")
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info("Log file: %s", log_path)
    except OSError as exc:
        logger.warning("Could not open log file %s: %s", log_path, exc)
    return logger


def _progress(logger: logging.Logger, done: int, total: int) -> None:
    percent = 100 if total == 0 else int(done * 100 / total)
    width = 24
    filled = width if total == 0 else int(width * done / total)
    bar = "#" * filled + "-" * (width - filled)
    logger.info("Progress: [%s] %3d%% (%d/%d archives)", bar, percent, done, total)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract supported archives in configured output_dir without confirmations; .unitypackage files are never extracted."
    )
    parser.add_argument("--config", help="Path to config.yml/config.yaml (default: repository root config file)")
    parser.add_argument("--log-file", help="Override log file (default: output_dir/.extract_archives.log)")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    try:
        config_path, output_dir = load_config(args.config, script_dir, project_root)
        output_dir.mkdir(parents=True, exist_ok=True)
    except (ExtractionError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    logger = make_logger(output_dir, args.log_file)
    logger.info("Configuration: %s", config_path)
    logger.info("Output directory: %s", output_dir)
    try:
        archives, unity_ignored = discover_archives(output_dir)
    except OSError as exc:
        logger.exception("Could not scan output_dir: %s", exc)
        return 2

    if unity_ignored:
        logger.info("Ignoring %d .unitypackage file(s); these are never extracted.", unity_ignored)
    total = len(archives)
    if total == 0:
        logger.info("No eligible archives found.")
        _progress(logger, 0, 0)
        return 0

    logger.info("Found %d eligible archive(s).", total)
    _progress(logger, 0, total)
    failed = 0
    extracted_files = 0
    replaced_files = 0
    skipped_files = 0
    for index, (source, suffix) in enumerate(archives, start=1):
        relative = source.relative_to(output_dir).as_posix()
        logger.info("Starting archive %d/%d: %s", index, total, relative)
        try:
            result = extract_archive(source, suffix)
            extracted_files += result.extracted
            replaced_files += result.replaced
            skipped_files += result.skipped_identical
            logger.info(
                "Completed %d/%d: %s — extracted %d, replaced %d (previous versions timestamped), skipped identical %d.",
                index, total, relative, result.extracted, result.replaced, result.skipped_identical,
            )
        except Exception as exc:
            failed += 1
            logger.error("FAILED %d/%d: %s — %s", index, total, relative, exc, exc_info=True)
        finally:
            _progress(logger, index, total)

    logger.info(
        "Finished: %d archive(s), %d extracted file(s), %d replaced file(s), %d identical file(s) skipped, %d failed archive(s).",
        total, extracted_files, replaced_files, skipped_files, failed,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
