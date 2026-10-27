# SPDX-License-Identifier: GPL-3.0-only
"""Safe, non-destructive extraction helpers for Local Dex's Extra Tools page.

Only Python's standard library is used. Original archive files are never changed.
"""
from __future__ import annotations

import gzip
import hashlib
import errno
import json
import os
import shutil
import stat
import tarfile
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable

MAX_SELECTED_ARCHIVES = 1000
MAX_ARCHIVE_ENTRIES = 200_000
MAX_UNCOMPRESSED_BYTES = 200 * 1024**3  # 200 GiB per archive
COPY_CHUNK = 1024 * 1024

# Longest suffixes must be tested first.
ARCHIVE_SUFFIXES = ('.unitypackage', '.tar.gz', '.tgz', '.tar', '.zip', '.gz', '.7z', '.rar')
SUPPORTED_SUFFIXES = {'.unitypackage', '.tar.gz', '.tgz', '.tar', '.zip', '.gz'}


class ArchiveExtractionError(Exception):
    """Raised when an archive cannot be extracted safely."""


def archive_suffix(filename: str) -> str:
    lowered = filename.lower()
    return next((suffix for suffix in ARCHIVE_SUFFIXES if lowered.endswith(suffix)), '')


def archive_stem(path: Path) -> str:
    suffix = archive_suffix(path.name)
    stem = path.name[:-len(suffix)] if suffix else path.stem
    stem = stem.rstrip(' .')
    return stem or f'{path.name}_extracted'


def archive_id(relative_path: str) -> str:
    """Return a stable opaque ID; API clients never submit filesystem paths."""
    return hashlib.sha256(relative_path.replace('\\', '/').encode('utf-8')).hexdigest()[:24]


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _history_path(history_file: Path | None = None) -> Path:
    """Return the local metadata path used to remember successful extractions."""
    return Path(history_file) if history_file is not None else Path(__file__).resolve().parent / '.localdex' / 'archive_extractions.json'


def _read_history(history_file: Path) -> dict[str, dict]:
    try:
        data = json.loads(history_file.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items()
            if isinstance(key, str) and isinstance(value, dict)}


def _write_history(history_file: Path, history: dict[str, dict]) -> None:
    """Atomically persist extraction dates outside the downloaded asset library."""
    history_file.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', newline='\n', dir=history_file.parent,
            prefix='.archive-extractions-', suffix='.tmp', delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(history, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, history_file)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)


def list_archives(library: Path, history_file: Path | None = None) -> list[dict]:
    """List archive files and prior extraction dates without following symlinks."""
    root = Path(library).expanduser().resolve()
    if not root.is_dir():
        return []
    history = _read_history(_history_path(history_file))

    results: list[dict] = []
    for path in root.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        parts = Path(relative).parts
        if any(part == '.localdex' or part.startswith('.localdex-extract-') for part in parts):
            continue
        suffix = archive_suffix(path.name)
        if not suffix or not _inside(root, path):
            continue
        destination = path.parent / archive_stem(path)
        try:
            source_stat = path.stat()
            size = source_stat.st_size
        except OSError:
            continue
        identifier = archive_id(relative)
        record = history.get(identifier, {})
        last_extracted_at = None
        if (record.get('source_size') == size
                and record.get('source_mtime_ns') == source_stat.st_mtime_ns
                and isinstance(record.get('last_extracted_at'), str)):
            last_extracted_at = record['last_extracted_at']
        results.append({
            'id': identifier,
            'name': path.name,
            'relative_path': relative,
            'package': parts[0] if len(parts) > 1 else '(library root)',
            'extension': suffix,
            'size': size,
            'supported': suffix in SUPPORTED_SUFFIXES,
            'destination_exists': destination.exists() or destination.is_symlink(),
            'destination': destination.relative_to(root).as_posix(),
            'last_extracted_at': last_extracted_at,
        })
    results.sort(key=lambda item: (item['package'].casefold(), item['relative_path'].casefold()))
    return results


def _safe_member_path(root: Path, name: str) -> Path:
    """Map an archive member to a path below root, rejecting traversal/drive paths."""
    if not isinstance(name, str) or not name or '\x00' in name:
        raise ArchiveExtractionError('Archive contains an invalid empty or NUL path.')
    normalized = name.replace('\\', '/')
    member = PurePosixPath(normalized)
    if member.is_absolute() or any(part == '..' for part in member.parts):
        raise ArchiveExtractionError(f'Unsafe archive path rejected: {name[:160]}')
    # Colons are forbidden in every component to reject drive prefixes and NTFS ADS paths.
    if any(':' in part for part in member.parts):
        raise ArchiveExtractionError(f'Unsafe archive path rejected: {name[:160]}')
    parts = [part for part in member.parts if part not in ('', '.')]
    if not parts:
        return root
    target = root.joinpath(*parts)
    if not _inside(root, target):
        raise ArchiveExtractionError(f'Unsafe archive path rejected: {name[:160]}')
    return target


def _check_archive_size(count: int, total: int) -> None:
    if count > MAX_ARCHIVE_ENTRIES:
        raise ArchiveExtractionError(f'Archive contains more than {MAX_ARCHIVE_ENTRIES:,} entries.')
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ArchiveExtractionError('Archive exceeds the 200 GiB uncompressed safety limit.')


def _copy_limited(source: BinaryIO, target: Path, expected_size: int, current_total: int) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open('xb') as output:
        while True:
            chunk = source.read(COPY_CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > expected_size or current_total + written > MAX_UNCOMPRESSED_BYTES:
                raise ArchiveExtractionError('Archive data exceeds its declared or allowed size.')
            output.write(chunk)
    if written != expected_size:
        raise ArchiveExtractionError('Archive entry size does not match its directory record.')
    return written


def _extract_zip(source: Path, destination: Path) -> tuple[int, int]:
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        total_expected = sum(info.file_size for info in entries if not info.is_dir())
        _check_archive_size(len(entries), total_expected)
        safe_entries: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in entries:
            target = _safe_member_path(destination, info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK or mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ArchiveExtractionError(f'Links and special files are not allowed: {info.filename[:160]}')
            if info.is_dir() or mode == stat.S_IFDIR:
                target.mkdir(parents=True, exist_ok=True)
                continue
            if info.file_size < 0:
                raise ArchiveExtractionError('Archive contains an invalid file size.')
            safe_entries.append((info, target))
        count = 0
        written_total = 0
        for info, target in safe_entries:
            with archive.open(info, 'r') as stream:
                written_total += _copy_limited(stream, target, info.file_size, written_total)
            count += 1
        return count, written_total


def _extract_tar(source: Path, destination: Path) -> tuple[int, int]:
    with tarfile.open(source, mode='r:*') as archive:
        entries = archive.getmembers()
        total_expected = sum(member.size for member in entries if member.isfile())
        _check_archive_size(len(entries), total_expected)
        safe_entries: list[tuple[tarfile.TarInfo, Path]] = []
        for member in entries:
            target = _safe_member_path(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                if member.size < 0:
                    raise ArchiveExtractionError('Archive contains an invalid file size.')
                safe_entries.append((member, target))
            else:
                raise ArchiveExtractionError(f'Links and special files are not allowed: {member.name[:160]}')
        count = 0
        written_total = 0
        for member, target in safe_entries:
            stream = archive.extractfile(member)
            if stream is None:
                raise ArchiveExtractionError(f'Could not read archive entry: {member.name[:160]}')
            with stream:
                written_total += _copy_limited(stream, target, member.size, written_total)
            count += 1
        return count, written_total


def _extract_gzip(source: Path, destination: Path) -> tuple[int, int]:
    # A plain .gz is a single compressed file, unlike .tar.gz and .tgz.
    output_name = archive_stem(source)
    target = destination / output_name
    with gzip.open(source, 'rb') as stream:
        # Gzip has no reliable declared uncompressed size; enforce the limit while streaming.
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with target.open('xb') as output:
            while True:
                chunk = stream.read(COPY_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UNCOMPRESSED_BYTES:
                    raise ArchiveExtractionError('Gzip data exceeds the 200 GiB safety limit.')
                output.write(chunk)
    return 1, written


def _extract_to_temp(source: Path, temporary: Path, suffix: str) -> tuple[int, int]:
    if suffix == '.zip':
        return _extract_zip(source, temporary)
    if suffix in ('.unitypackage', '.tar.gz', '.tgz', '.tar'):
        return _extract_tar(source, temporary)
    if suffix == '.gz':
        return _extract_gzip(source, temporary)
    raise ArchiveExtractionError(f'Unsupported archive format: {suffix or source.suffix}')


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            chunk = stream.read(COPY_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _same_file_content(left: Path, right: Path) -> bool:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        return _file_digest(left) == _file_digest(right)
    except OSError:
        return False


def _timestamped_path(path: Path, stamp: str, directory: bool = False) -> Path:
    """Choose a unique sibling path for preserving an older file or directory."""
    if directory:
        base_name = f'{path.name}_{stamp}'
        suffix = ''
        stem = base_name
    else:
        suffix = path.suffix
        stem = f'{path.stem}_{stamp}'
    candidate = path.with_name(stem + suffix)
    index = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f'{stem}_{index}{suffix}')
        index += 1
    return candidate


def _preserve_path(path: Path, stamp: str) -> Path:
    """Rename a conflicting existing path without deleting its contents."""
    if path.is_symlink():
        raise ArchiveExtractionError(f'Refusing to replace a symbolic link: {path.name}')
    if path.is_file():
        backup = _timestamped_path(path, stamp)
    elif path.is_dir():
        backup = _timestamped_path(path, stamp, directory=True)
    else:
        raise ArchiveExtractionError(f'Refusing to replace a special filesystem entry: {path.name}')
    path.rename(backup)
    return backup


def _ensure_merge_directory(destination: Path, directory: Path, stamp: str) -> int:
    """Ensure a directory exists, preserving a conflicting file if necessary."""
    backups = 0
    try:
        relative = directory.relative_to(destination)
    except ValueError as exc:
        raise ArchiveExtractionError('Extracted directory escaped its destination.') from exc
    current = destination
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ArchiveExtractionError(f'Refusing to follow a symbolic link: {current.name}')
        if current.exists() and current.is_file():
            _preserve_path(current, stamp)
            backups += 1
        elif current.exists() and not current.is_dir():
            raise ArchiveExtractionError(f'Refusing to replace a special filesystem entry: {current.name}')
        current.mkdir(exist_ok=True)
    return backups


def _copy_file_atomically(source: Path, target: Path) -> None:
    """Copy to a temporary sibling and atomically publish the completed file."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='wb', dir=target.parent, prefix='.localdex-merge-', suffix='.tmp', delete=False,
        ) as output:
            temporary = Path(output.name)
            with source.open('rb') as input_stream:
                shutil.copyfileobj(input_stream, output, length=COPY_CHUNK)
            output.flush()
            os.fsync(output.fileno())
        shutil.copystat(source, temporary, follow_symlinks=False)
        if target.exists() or target.is_symlink():
            raise ArchiveExtractionError(f'Target changed while merging: {target.name}')
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _merge_extracted_tree(extracted: Path, destination: Path, stamp: str) -> tuple[int, int, int]:
    """Merge a new extraction, timestamping old files only when contents differ.

    Files absent from the new archive are intentionally retained. Existing files with
    identical contents are left untouched. When contents differ, the old file is renamed
    to ``name_YYYYMMDD_HHMMSS.ext`` before the new version is installed.
    """
    if destination.is_symlink() or not destination.is_dir():
        raise ArchiveExtractionError('The existing extraction destination is not a regular directory.')

    backups = 0
    added = 0
    updated = 0

    directories = sorted(
        (path for path in extracted.rglob('*') if path.is_dir() and not path.is_symlink()),
        key=lambda path: (len(path.relative_to(extracted).parts), path.as_posix().casefold()),
    )
    for incoming_dir in directories:
        relative = incoming_dir.relative_to(extracted)
        backups += _ensure_merge_directory(destination, destination / relative, stamp)

    incoming_files = sorted(
        (path for path in extracted.rglob('*') if path.is_file() and not path.is_symlink()),
        key=lambda path: path.relative_to(extracted).as_posix().casefold(),
    )
    for incoming in incoming_files:
        relative = incoming.relative_to(extracted)
        target = destination / relative
        backups += _ensure_merge_directory(destination, target.parent, stamp)

        if target.is_symlink():
            raise ArchiveExtractionError(f'Refusing to replace a symbolic link: {target.name}')
        if target.exists() and target.is_dir():
            _preserve_path(target, stamp)
            backups += 1
            target_was_added = False
        elif target.exists() and target.is_file():
            if _same_file_content(target, incoming):
                continue
            _preserve_path(target, stamp)
            backups += 1
            target_was_added = False
        elif target.exists():
            raise ArchiveExtractionError(f'Refusing to replace a special filesystem entry: {target.name}')
        else:
            target_was_added = True

        _copy_file_atomically(incoming, target)
        if target_was_added:
            added += 1
        else:
            updated += 1

    return added, updated, backups


def _is_retryable_directory_rename_error(error: OSError) -> bool:
    """Recognize transient Windows sharing/access errors from publishing a folder."""
    winerror = getattr(error, 'winerror', None)
    return (
        isinstance(error, PermissionError)
        or winerror in (5, 32, 33)  # access denied, sharing violation, lock violation
        or error.errno in (errno.EACCES, errno.EPERM, errno.EBUSY)
    )


def _publish_new_extraction(
    temporary: Path,
    destination: Path,
    stamp: str,
    allow_merge: bool,
) -> dict:
    """Publish a staged extraction with Windows lock retries and a copy fallback.

    The normal path is an atomic directory rename. Some Windows file scanners can
    briefly lock a newly-written directory, so retry access/sharing errors before
    falling back to a safe copy. If another process creates the destination during
    this operation, merge only when the user explicitly confirmed that archive.
    """
    delays = (0.15, 0.35, 0.7, 1.2)
    last_error: OSError | None = None

    def handle_existing_destination() -> dict:
        if destination.is_symlink() or not destination.is_dir():
            raise ArchiveExtractionError(
                'The extraction destination appeared during extraction but is not a regular directory.'
            )
        if not allow_merge:
            return {
                'action': 'skipped',
                'message': 'Destination appeared during extraction; confirmation to compare and merge was not provided.',
            }
        added, updated, backups = _merge_extracted_tree(temporary, destination, stamp)
        return {
            'action': 'merged', 'added': added, 'updated': updated, 'backups': backups,
            'message': (f'Compared extracted files: {added:,} added, {updated:,} updated, '
                        f'{backups:,} timestamped backup(s) preserved. Existing files absent from the archive were kept.'),
        }

    for attempt in range(len(delays) + 1):
        if destination.exists() or destination.is_symlink():
            # If the rename actually completed before Windows reported an error,
            # the staging folder will no longer exist and the final folder is ours.
            if not temporary.exists() and destination.is_dir() and not destination.is_symlink():
                return {'action': 'renamed'}
            return handle_existing_destination()
        try:
            temporary.rename(destination)
            return {'action': 'renamed'}
        except OSError as error:
            last_error = error
            if destination.exists() or destination.is_symlink():
                continue
            if not _is_retryable_directory_rename_error(error):
                raise
            if attempt < len(delays):
                time.sleep(delays[attempt])

    # The destination may have appeared while retries were running.
    if destination.exists() or destination.is_symlink():
        return handle_existing_destination()

    # Last resort: create the destination ourselves and copy the staged files.
    # mkdir() is intentionally separate so a concurrent destination creation is
    # detected rather than merged or overwritten without confirmation.
    try:
        destination.mkdir()
    except FileExistsError:
        return handle_existing_destination()

    try:
        shutil.copytree(temporary, destination, dirs_exist_ok=True, copy_function=shutil.copy2)
    except Exception as copy_error:
        # This destination did not exist before this operation; remove the partial
        # copy so the next scan does not mistake it for a completed extraction.
        shutil.rmtree(destination, ignore_errors=True)
        detail = f'Could not publish extraction after directory rename retries ({last_error}).'
        raise ArchiveExtractionError(f'{detail} Copy fallback failed: {copy_error}') from copy_error

    shutil.rmtree(temporary, ignore_errors=True)
    return {'action': 'copied'}


def extract_selected_archives(
    library: Path,
    selected_ids: list[str],
    history_file: Path | None = None,
    replace_existing_ids: set[str] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    """Extract selected archives; report per-archive progress through an optional callback."""
    root = Path(library).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('The configured SyntyLibrary directory does not exist.')
    if not isinstance(selected_ids, list) or not selected_ids:
        raise ValueError('Select at least one archive.')
    if len(selected_ids) > MAX_SELECTED_ARCHIVES:
        raise ValueError(f'Select no more than {MAX_SELECTED_ARCHIVES:,} archives at once.')
    ids: list[str] = []
    for item in selected_ids:
        if not isinstance(item, str) or len(item) != 24 or any(c not in '0123456789abcdef' for c in item):
            raise ValueError('Invalid archive selection.')
        if item not in ids:
            ids.append(item)
    replace_ids = replace_existing_ids or set()
    if not isinstance(replace_ids, set) or any(item not in ids for item in replace_ids):
        raise ValueError('Invalid confirmation list for existing extraction folders.')

    history_file = _history_path(history_file)
    history = _read_history(history_file)
    available = {item['id']: item for item in list_archives(root, history_file)}
    results: list[dict] = []

    def emit_progress(event: dict) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(event)
        except Exception:
            # A UI/progress listener must never interrupt a filesystem operation.
            pass

    def record_result(result: dict) -> None:
        results.append(result)
        emit_progress({'event': 'complete', 'result': result})

    for index, identifier in enumerate(ids, start=1):
        item = available.get(identifier)
        display_name = item['relative_path'] if item else 'Unknown archive'
        emit_progress({'event': 'start', 'index': index, 'total': len(ids), 'id': identifier, 'name': display_name})
        if item is None:
            record_result({'id': identifier, 'status': 'failed', 'name': 'Unknown archive',
                            'message': 'The archive is no longer present. Refresh the list.'})
            continue
        name = item['relative_path']
        if not item['supported']:
            record_result({'id': identifier, 'status': 'failed', 'name': name,
                            'message': f"Unsupported archive format: {item['extension']}"})
            continue
        candidate = root / item['relative_path']
        if candidate.is_symlink() or not candidate.is_file() or not _inside(root, candidate):
            record_result({'id': identifier, 'status': 'failed', 'name': name,
                            'message': 'Archive source is missing, linked, or outside the library.'})
            continue
        source = candidate.resolve()
        destination = source.parent / archive_stem(source)
        if not _inside(root, destination):
            record_result({'id': identifier, 'status': 'failed', 'name': name,
                            'message': 'Extraction destination is outside the library.'})
            continue
        destination_exists = destination.exists() or destination.is_symlink()
        allow_merge = identifier in replace_ids
        if destination_exists and not allow_merge:
            record_result({'id': identifier, 'status': 'skipped', 'name': name,
                            'destination': destination.relative_to(root).as_posix(),
                            'message': 'Destination already exists; confirmation to compare and merge was not provided.'})
            continue
        if destination_exists and (destination.is_symlink() or not destination.is_dir()):
            record_result({'id': identifier, 'status': 'failed', 'name': name,
                            'message': 'The existing extraction destination is not a regular directory.'})
            continue

        temporary: Path | None = None
        try:
            temporary = Path(tempfile.mkdtemp(prefix='.localdex-extract-', dir=str(source.parent)))
            count, byte_count = _extract_to_temp(source, temporary, item['extension'])
            extracted_at = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            stamp = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')
            if destination.exists() or destination.is_symlink():
                if identifier not in replace_ids:
                    record_result({'id': identifier, 'status': 'skipped', 'name': name,
                                    'destination': destination.relative_to(root).as_posix(),
                                    'message': 'Destination appeared during extraction; confirmation was not provided.'})
                    continue
                added, updated, backups = _merge_extracted_tree(temporary, destination, stamp)
                message = (f'Compared {count:,} extracted files: {added:,} added, {updated:,} updated, '
                           f'{backups:,} timestamped backup(s) preserved. Existing files absent from the archive were kept.')
            else:
                publication = _publish_new_extraction(
                    temporary, destination, stamp, allow_merge=identifier in replace_ids,
                )
                if publication['action'] == 'skipped':
                    record_result({'id': identifier, 'status': 'skipped', 'name': name,
                                    'destination': destination.relative_to(root).as_posix(),
                                    'message': publication['message']})
                    continue
                if publication['action'] == 'merged':
                    added = publication['added']
                    updated = publication['updated']
                    backups = publication['backups']
                    message = publication['message']
                else:
                    added, updated, backups = count, 0, 0
                    message = f'Extracted {count:,} files ({byte_count:,} bytes).'
                    if publication['action'] == 'copied':
                        message += (' Windows temporarily blocked the directory rename; '
                                    'the extraction was published using a file-copy fallback after retries.')
            try:
                source_stat = source.stat()
                history[identifier] = {
                    'last_extracted_at': extracted_at,
                    'source_size': source_stat.st_size,
                    'source_mtime_ns': source_stat.st_mtime_ns,
                }
                _write_history(history_file, history)
                history_message = ''
            except OSError as history_error:
                history_message = f' Extraction date could not be saved: {history_error}'
            record_result({'id': identifier, 'status': 'extracted', 'name': name,
                            'destination': destination.relative_to(root).as_posix(),
                            'last_extracted_at': extracted_at,
                            'files': count, 'bytes': byte_count,
                            'added': added, 'updated': updated, 'backups': backups,
                            'message': f'{message}{history_message}'})
        except Exception as exc:
            if destination.exists() and not allow_merge:
                status = 'skipped'
                message = 'Destination already exists; confirmation to compare and merge was not provided.'
            else:
                status = 'failed'
                message = str(exc) or type(exc).__name__
            record_result({'id': identifier, 'status': status, 'name': name, 'message': message})
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    counts = {status: sum(1 for item in results if item['status'] == status)
              for status in ('extracted', 'skipped', 'failed')}
    return {'ok': counts['failed'] == 0, 'counts': counts, 'results': results}
