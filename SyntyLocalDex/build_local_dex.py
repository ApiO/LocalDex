#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Non-destructive, incremental Synty library indexer. Python >=3.10.

Run without arguments when installed in SyntyLocalDex beside SyntyLibrary:
  python build_local_dex.py
  python build_local_dex.py --skip-unity-contents

The local index is saved in SyntyLocalDex/.localdex. Downloaded assets are
read-only and are not changed or extracted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tarfile
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator

DEX_DIR = Path(__file__).resolve().parent
DEFAULT_LIBRARY = DEX_DIR.parent / 'SyntyLibrary'
DEFAULT_INDEX_DIR = DEX_DIR / '.localdex'

SCHEMA_VERSION = 3
VIEWABLE_ASSETS_SQL = "(inner_path <> '' OR (inner_path = '' AND kind NOT IN ('Archive', 'Unity package', 'Document', 'Other')))"
ASSET_SUFFIXES = {'.fbx', '.obj', '.glb', '.gltf', '.blend', '.dae', '.3ds', '.stl', '.abc', '.usd', '.usdz', '.prefab', '.unity', '.uasset', '.umap', '.anim', '.controller', '.overridecontroller', '.mat', '.material', '.shader', '.hlsl', '.cginc', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.tga', '.tif', '.tiff', '.exr', '.psd', '.svg', '.wav', '.ogg', '.mp3', '.flac', '.mp4', '.webm', '.mov', '.cs', '.cpp', '.h', '.txt', '.json', '.asset', '.vfx', '.uxml', '.uss', '.aseprite', '.atlas'}
ZIP_EXTENSIONS = {'.zip'}
OTHER_ARCHIVES = {'.rar', '.7z', '.tar', '.gz'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.avif'}
MAX_COVER_BYTES = 8_000_000
IGNORED_FILES = {'.ds_store', 'thumbs.db', 'desktop.ini'}
THEMES = {
    'Sci-Fi': ('sci fi', 'scifi', 'science fiction', 'cyber', 'space', 'futuristic'),
    'Fantasy': ('fantasy', 'wizard', 'magic', 'elf', 'elven', 'dwarf', 'knights', 'orcs', 'goblin', 'dragon'),
    'Nature': ('nature', 'alpine', 'forest', 'meadow', 'swamp', 'desert', 'biome', 'jungle', 'woodland'),
    'Military': ('military', 'army', 'soldier', 'warfare'),
    'Apocalypse': ('apocalypse', 'post apoc', 'zombie', 'wasteland'),
    'Urban': ('city', 'urban', 'street', 'modern', 'town'),
    'Historic': ('ancient', 'medieval', 'viking', 'pirate', 'empire', 'roman'),
}
MODEL_EXTENSIONS = {'.fbx', '.obj', '.glb', '.gltf', '.blend', '.dae', '.3ds', '.stl', '.abc', '.usd', '.usdz'}
TEXTURE_HINTS = ('texture', 'textures', 'albedo', 'diffuse', 'normal', 'roughness', 'metallic', 'emissive', 'specular', 'mask', 'material')
PATH_CATEGORIES = {
    'Character': ('characters', 'character', 'humanoids', 'people', 'npcs', 'heroes'),
    'Vehicle': ('vehicles', 'vehicle', 'cars', 'trucks', 'aircraft', 'ships'),
    'Prop': ('props', 'prop', 'weapons', 'equipment', 'furniture', 'items'),
    'Environment': ('environment', 'environments', 'buildings', 'architecture', 'terrain', 'foliage'),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def stable_id(value: str) -> str:
    return hashlib.blake2b(value.encode('utf-8'), digest_size=12).hexdigest()


def clean_title(value: str) -> str:
    value = re.sub(r'[_-]+', ' ', value)
    value = re.sub(r'(?i)\.(fbx|obj|glb|gltf|prefab|unity|uasset)$', '', value)
    return re.sub(r'\s+', ' ', value).strip()


def taxonomy(pack_name: str) -> tuple[str, str]:
    u = pack_name.upper()
    collection = next((c for c in ('POLYGON', 'ANIMATION', 'INTERFACE', 'SIMPLE', 'SIDEKICK') if u.startswith(c)), None)
    if collection is None:
        collection = 'SIDEKICK' if 'SIDEKICK' in u else 'OTHER'
    s = pack_name.lower().replace('-', ' ').replace('_', ' ')
    theme = next((t for t, words in THEMES.items() if any(w in s for w in words)), 'Other')
    return collection.title(), theme


def classify(pack_name: str, rel: str, inner: str = '') -> tuple[str, str, str]:
    """Returns kind, category, engine; classifications are heuristics."""
    full = (inner or rel).replace('\\', '/')
    low = full.lower()
    extension = PurePosixPath(full).suffix.lower()
    if extension == '.zip' or extension in OTHER_ARCHIVES:
        return 'Archive', 'Package', 'Any'
    if extension == '.unitypackage':
        return 'Unity package', 'Package', 'Unity'
    if extension in ('.uasset', '.umap'):
        return ('Level' if extension == '.umap' else 'Unreal asset'), '3D / project', 'Unreal'
    if extension == '.unity':
        return 'Scene', 'Environment', 'Unity'
    if extension in ('.prefab',):
        kind = 'Prefab'
    elif extension in ('.anim', '.controller', '.overridecontroller'):
        kind = 'Animation'
    elif extension in MODEL_EXTENSIONS:
        kind = 'Model'
        if 'animation' in low or ('ANIMATION' in pack_name.upper()):
            kind = 'Animation'
    elif extension in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.tga', '.tif', '.tiff', '.exr', '.psd', '.svg', '.aseprite', '.atlas'):
        kind = 'Texture' if any(w in low for w in TEXTURE_HINTS) else 'Image'
        if 'INTERFACE' in pack_name.upper() or any(w in low for w in ('sprites', 'icons', 'hud', 'gui', 'ui/')):
            kind = 'UI / sprite'
    elif extension in ('.wav', '.ogg', '.mp3', '.flac'):
        kind = 'Audio'
    elif extension in ('.mp4', '.webm', '.mov'):
        kind = 'Video'
    elif extension in ('.mat', '.material', '.shader', '.hlsl', '.cginc', '.vfx'):
        kind = 'Material / shader'
    elif extension in ('.cs', '.cpp', '.h', '.uxml', '.uss'):
        kind = 'Code'
    elif extension in ('.txt', '.md', '.pdf', '.json'):
        kind = 'Document'
    else:
        kind = 'Other'
    category = next((category for category, names in PATH_CATEGORIES.items()
                     if any(re.search(r'(?<![a-z])' + re.escape(word) + r'(?![a-z])', low) for word in names)), '')
    if not category:
        category = ('Animation' if kind == 'Animation' else 'Interface' if kind == 'UI / sprite'
                    else 'Texture' if kind == 'Texture' else 'Unsorted')
    engine = ('Unreal' if any(w in low for w in ('unreal', '/ue4/', '/ue5/'))
              else 'Unity' if any(w in low for w in ('unity', '/assets/')) or extension in ('.prefab', '.anim', '.controller', '.mat', '.cs')
              else 'Any')
    return kind, category, engine


def interesting_member(name: str) -> bool:
    name = name.replace('\\', '/')
    if name.startswith('/') or '\x00' in name or '..' in PurePosixPath(name).parts:
        return False
    if len(name) > 700:
        return False
    suffix = PurePosixPath(name).suffix.lower()
    if PurePosixPath(name).name.lower() in IGNORED_FILES or suffix == '.meta':
        return False
    return suffix in ASSET_SUFFIXES or suffix in ZIP_EXTENSIONS or suffix in OTHER_ARCHIVES


def preview_rank(rel: str, size: int) -> int:
    """Prefer explicit pack cover artwork; never mistake texture maps for covers."""
    s = rel.replace('\\', '/').lower()
    name = PurePosixPath(s).name
    if PurePosixPath(s).suffix not in IMAGE_EXTENSIONS or size <= 0 or size > 7_000_000:
        return -1
    if any(w in s for w in ('textures/', 'materials/', 'sprites/', '_normal', '_albedo', 'diffuse', '_mask')):
        return -1
    score = 0
    if any(w in name for w in ('cover', 'thumbnail', 'promo', 'keyart', 'banner', 'screenshot')):
        score += 100
    if 'preview' in name:
        score += 45
    score += max(0, 30 - s.count('/') * 12)
    return score if score >= 40 else -1


DDL = '''
CREATE TABLE IF NOT EXISTS packs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, folder TEXT NOT NULL UNIQUE,
  collection TEXT NOT NULL, theme TEXT NOT NULL, cover TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sources (
  pack_id TEXT NOT NULL, relative_path TEXT NOT NULL,
  size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, mode TEXT NOT NULL,
  scanned_at TEXT NOT NULL, warning TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(pack_id, relative_path)
);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, pack_id TEXT NOT NULL, source_rel TEXT NOT NULL,
  inner_path TEXT NOT NULL, name TEXT NOT NULL, title TEXT NOT NULL,
  kind TEXT NOT NULL, category TEXT NOT NULL, engine TEXT NOT NULL,
  ext TEXT NOT NULL, bytes INTEGER NOT NULL, search_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_pack ON assets(pack_id);
CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);
CREATE INDEX IF NOT EXISTS idx_assets_source ON assets(pack_id, source_rel);
CREATE INDEX IF NOT EXISTS idx_assets_engine ON assets(engine);
CREATE INDEX IF NOT EXISTS idx_packs_collection ON packs(collection);
'''


def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return conn


def add_item(conn: sqlite3.Connection, pack_id: str, pack_name: str, source_rel: str,
             inner_path: str, size: int) -> None:
    name = PurePosixPath(inner_path or source_rel).name
    kind, category, engine = classify(pack_name, source_rel, inner_path)
    ident = stable_id(f'{pack_id}\0{source_rel}\0{inner_path}')
    ext = PurePosixPath(name).suffix.lower()
    searchable = ' '.join([name, clean_title(name), inner_path, source_rel, pack_name, kind, category, engine]).lower()
    conn.execute('''INSERT OR IGNORE INTO assets
      (id,pack_id,source_rel,inner_path,name,title,kind,category,engine,ext,bytes,search_text)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
      (ident, pack_id, source_rel, inner_path, name, clean_title(name), kind, category, engine, ext,
       size, searchable))


def zip_entries(path: Path, limit: int) -> Iterator[tuple[str,int]]:
    with zipfile.ZipFile(path) as zf:
        if len(zf.infolist()) > limit:
            raise ValueError(f'ZIP contains over {limit:,} members; skipped its contents')
        for info in zf.infolist():
            if info.is_dir() or not interesting_member(info.filename):
                continue
            yield info.filename.replace('\\', '/'), info.file_size


def unity_entries(path: Path, limit: int) -> Iterator[tuple[str,int]]:
    """Stream only UnityPackage GUID/pathname headers. No asset content is extracted.

    Unity .unitypackage is gzip tar, with <guid>/pathname containing original asset path.
    Streaming avoids buffering an entire huge archive.
    """
    count = 0
    with tarfile.open(path, mode='r|gz') as stream:
        for member in stream:
            if not member.isfile() or not member.name.endswith('/pathname'):
                continue
            count += 1
            if count > limit:
                raise ValueError(f'Unity archive contains over {limit:,} pathname entries')
            if member.size > 8192:
                continue
            opened = stream.extractfile(member)
            if opened is None:
                continue
            original = opened.read(8193).decode('utf-8-sig', errors='replace').strip('\x00\r\n ')
            if interesting_member(original):
                yield original, 0


def first_root_image(folder: Path, candidates: list[Path]) -> Path | None:
    """First eligible image *directly inside* this package folder.

    Deterministic, case-insensitive filename ordering. Nested images and archive
    members are not considered; oversized/empty/unreadable images are skipped.
    """
    for image in sorted(candidates, key=lambda f: (f.name.casefold(), f.name)):
        if image.parent != folder or image.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            if 0 < image.stat().st_size <= MAX_COVER_BYTES:
                return image
        except OSError:
            continue
    return None


def cache_root_cover(root: Path, local_dir: Path, pack_id: str, image: Path) -> str:
    """Cache the chosen image outside the library, invalidating on modifications."""
    import shutil
    src_stat = image.stat()
    # Versioned cache name prevents browsers (max-age=3600) from showing stale art.
    key = stable_id(f'{image.relative_to(root).as_posix()}:{src_stat.st_mtime_ns}:{src_stat.st_size}')
    destination = local_dir / 'covers' / f'{pack_id}-root-{key}{image.suffix.lower()}'
    destination.parent.mkdir(exist_ok=True)
    if (not destination.is_file() or destination.stat().st_size != src_stat.st_size
            or destination.stat().st_mtime_ns != src_stat.st_mtime_ns):
        shutil.copyfile(image, destination)
        os.utime(destination, ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns))
    return destination.relative_to(local_dir).as_posix()


def pick_cover(root: Path, local_dir: Path, pack_id: str, candidates: list[Path], archives: list[Path]) -> str:
    """Cache an available pack cover. Read-only source, bounded-size copy."""
    import shutil
    best: tuple[int, Path] | None = None
    for f in candidates:
        try:
            score = preview_rank(f.relative_to(root).as_posix(), f.stat().st_size)
            if score > 0 and (best is None or score > best[0]):
                best = score, f
        except OSError:
            pass
    covers_dir = local_dir / 'covers'
    covers_dir.mkdir(exist_ok=True)
    if best is not None:
        f = best[1]
        dst = covers_dir / f'{pack_id}{f.suffix.lower()}'
        if not dst.exists() or dst.stat().st_mtime_ns != f.stat().st_mtime_ns:
            shutil.copyfile(f, dst)
            # The cached cover is generated metadata; keep its timestamp to compare later.
            import os
            os.utime(dst, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns))
        return dst.relative_to(local_dir).as_posix()

    # Best-effort ZIP cover; only archive entries suggesting pack cover art.
    for archive in archives[:20]:
        try:
            with zipfile.ZipFile(archive) as zf:
                choices = sorted(((-preview_rank(i.filename, i.file_size), i) for i in zf.infolist()
                                  if preview_rank(i.filename, i.file_size) >= 60), key=lambda x: x[0])
                if not choices:
                    continue
                info = choices[0][1]
                key = stable_id(f'{archive.relative_to(root)}:{info.CRC}:{info.file_size}')
                suffix = PurePosixPath(info.filename).suffix.lower()
                dst = covers_dir / f'{pack_id}-{key}{suffix}'
                if not dst.exists():
                    with zf.open(info) as inp, dst.open('wb') as out:
                        shutil.copyfileobj(inp, out, 128 * 1024)
                return dst.relative_to(local_dir).as_posix()
        except (OSError, zipfile.BadZipFile, RuntimeError):
            continue
    return ''


def build(root: Path, *, index_dir: Path | None = None, scan_unity: bool = True,
          max_entries: int = 80000, verbose: bool = True) -> dict:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f'Library folder does not exist: {root}')
    local = (Path(index_dir) if index_dir is not None else DEFAULT_INDEX_DIR).expanduser().resolve()
    if local == root or local.is_relative_to(root):
        raise ValueError('Index folder must be outside SyntyLibrary to keep the library read-only')
    local.mkdir(parents=True, exist_ok=True)
    db = connect_db(local / 'index.sqlite3')
    seen_packs: set[str] = set()
    scanned_sources = skipped_sources = failed_sources = 0
    start = time.monotonic()
    try:
        folders = sorted([p for p in root.iterdir() if p.is_dir() and not p.name.startswith('.')],
                         key=lambda p: p.name.casefold())
        for folder in folders:
            name = folder.name
            pack_id = stable_id(name.casefold())
            seen_packs.add(pack_id)
            collection, theme = taxonomy(name)
            db.execute('''INSERT INTO packs(id,name,folder,collection,theme)
                VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,folder=excluded.folder,collection=excluded.collection,theme=excluded.theme''',
                (pack_id, name, name, collection, theme))
            files = sorted((p for p in folder.rglob('*') if p.is_file() and not any(part.startswith('.') for part in p.relative_to(folder).parts)),
                           key=lambda p: str(p).casefold())
            seen_files: set[str] = set()
            zips: list[Path] = []
            preview_files: list[Path] = []
            if verbose:
                print(f'[PACK] {name} ({len(files)} local files)', flush=True)
            for p in files:
                rel = p.relative_to(root).as_posix()
                seen_files.add(rel)
                ext = p.suffix.lower()
                if ext == '.zip':
                    zips.append(p)
                elif ext in IMAGE_EXTENSIONS:
                    preview_files.append(p)
                try:
                    st = p.stat()
                    base_mode = 'zip' if ext in ZIP_EXTENSIONS else 'unity' if ext == '.unitypackage' and scan_unity else 'file'
                    mode = f'{base_mode}:v{SCHEMA_VERSION}'
                    old = db.execute('SELECT size, mtime_ns, mode FROM sources WHERE pack_id=? AND relative_path=?',
                                     (pack_id, rel)).fetchone()
                    if old and old['size'] == st.st_size and old['mtime_ns'] == st.st_mtime_ns and old['mode'] == mode:
                        skipped_sources += 1
                        continue
                    db.execute('DELETE FROM assets WHERE pack_id=? AND source_rel=?', (pack_id, rel))
                    add_item(db, pack_id, name, rel, '', st.st_size)
                    warning = ''
                    try:
                        if base_mode == 'zip':
                            for member, size in zip_entries(p, max_entries):
                                add_item(db, pack_id, name, rel, member, size)
                        elif base_mode == 'unity':
                            for member, size in unity_entries(p, max_entries):
                                add_item(db, pack_id, name, rel, member, size)
                    except (OSError, EOFError, tarfile.TarError, zipfile.BadZipFile, RuntimeError, ValueError) as ex:
                        warning = f'{type(ex).__name__}: {ex}'[:250]
                        failed_sources += 1
                        print(f'  [WARN] {p.name}: {warning}', file=sys.stderr)
                    db.execute('''INSERT INTO sources(pack_id,relative_path,size,mtime_ns,mode,scanned_at,warning)
                        VALUES (?,?,?,?,?,?,?) ON CONFLICT(pack_id,relative_path) DO UPDATE SET
                        size=excluded.size,mtime_ns=excluded.mtime_ns,mode=excluded.mode,
                        scanned_at=excluded.scanned_at,warning=excluded.warning''',
                        (pack_id, rel, st.st_size, st.st_mtime_ns, mode, utc_now(), warning))
                    db.commit()
                    scanned_sources += 1
                except OSError as ex:
                    failed_sources += 1
                    print(f'  [WARN] Cannot read {rel}: {ex}', file=sys.stderr)
            # Library may lose files only through external/manual deletion. Clean obsolete index
            # records; the original sync files themselves are never touched.
            for old in db.execute('SELECT relative_path FROM sources WHERE pack_id=?', (pack_id,)).fetchall():
                if old['relative_path'] not in seen_files:
                    db.execute('DELETE FROM assets WHERE pack_id=? AND source_rel=?', (pack_id, old['relative_path']))
                    db.execute('DELETE FROM sources WHERE pack_id=? AND relative_path=?', (pack_id, old['relative_path']))
            current = db.execute('SELECT cover FROM packs WHERE id=?', (pack_id,)).fetchone()['cover']
            root_image = first_root_image(folder, preview_files)
            if root_image is not None:
                # A new root-level image must override even a previously cached cover.
                cover = cache_root_cover(root, local, pack_id, root_image)
                if cover != current:
                    db.execute('UPDATE packs SET cover=? WHERE id=?', (cover, pack_id))
            elif (not current or not (local / current).is_file()
                  or Path(current).name.startswith(f'{pack_id}-root-')):
                # When the root image disappears, fall back to the original
                # artwork selection. Don't reopen archives on every steady-state scan.
                cover = pick_cover(root, local, pack_id, preview_files, zips)
                db.execute('UPDATE packs SET cover=? WHERE id=?', (cover, pack_id))
            db.commit()
        for row in db.execute('SELECT id FROM packs').fetchall():
            if row['id'] not in seen_packs:
                db.execute('DELETE FROM sources WHERE pack_id=?', (row['id'],))
                db.execute('DELETE FROM assets WHERE pack_id=?', (row['id'],))
                db.execute('DELETE FROM packs WHERE id=?', (row['id'],))
        db.commit()
        packages = [dict(r) for r in db.execute(f'''SELECT p.*,
          (SELECT COUNT(*) FROM sources s WHERE s.pack_id=p.id) AS files,
          (SELECT COUNT(*) FROM assets a WHERE a.pack_id=p.id AND {VIEWABLE_ASSETS_SQL}) AS assets,
          (SELECT COALESCE(SUM(s.size),0) FROM sources s WHERE s.pack_id=p.id) AS bytes
          FROM packs p ORDER BY p.name COLLATE NOCASE''').fetchall()]
        totals = db.execute(f'''SELECT COUNT(*) AS assets FROM assets WHERE {VIEWABLE_ASSETS_SQL}''').fetchone()
        kinds = [dict(r) for r in db.execute(f"SELECT kind AS name, COUNT(*) AS count FROM assets WHERE {VIEWABLE_ASSETS_SQL} GROUP BY kind ORDER BY count DESC").fetchall()]
        categories = [dict(r) for r in db.execute(f"SELECT category AS name, COUNT(*) AS count FROM assets WHERE {VIEWABLE_ASSETS_SQL} GROUP BY category ORDER BY count DESC").fetchall()]
        collections = dict(Counter(p['collection'] for p in packages))
        # The manifest keeps a relative library locator when the two folders
        # share a drive, so moving the whole project does not stale the index.
        try:
            library_locator = Path(os.path.relpath(root, local.parent)).as_posix()
        except ValueError:  # Windows: optional custom library on another drive
            library_locator = str(root)
        manifest = {
            'schema_version': SCHEMA_VERSION, 'generated_at': utc_now(),
            'library': library_locator,
            'stats': {'packs': len(packages), 'download_files': sum(p['files'] for p in packages),
                      'assets': totals['assets'], 'total_bytes': sum(p['bytes'] for p in packages),
                      'collections': collections, 'kinds': kinds, 'categories': categories,
                      'scanned_sources': scanned_sources, 'cached_sources': skipped_sources,
                      'failed_sources': failed_sources,
                      'duration_seconds': round(time.monotonic() - start, 1)},
            'packs': packages,
        }
        output = local / 'catalog.json'
        tmp = local / 'catalog.json.tmp'
        tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(output)
        if verbose:
            print(f"\nIndexed {len(packages)} packs, {totals['assets']:,} entries inside archives; "
                  f"{scanned_sources} scanned / {skipped_sources} unchanged / {failed_sources} warnings")
            print(f'Catalog: {output}\nDatabase: {local / "index.sqlite3"}')
        return manifest
    finally:
        db.close()


def main() -> int:
    if os.name != 'nt':
        print(
            'The LocalDex indexer is supported on Windows only. '
            'Linux support is provided for the standalone SyntyDownloader CLI.',
            file=sys.stderr,
        )
        return 2
    ap = argparse.ArgumentParser(description='Build an offline searchable index of downloaded Synty packs')
    ap.add_argument('--root', '--output', dest='root', type=Path, default=DEFAULT_LIBRARY,
                    help='Library directory (default: sibling ../SyntyLibrary)')
    ap.add_argument('--index-dir', type=Path, default=DEFAULT_INDEX_DIR,
                    help='Generated catalog directory (default: this Dex folder/.localdex)')
    ap.add_argument('--skip-unity-contents', action='store_true', help='Faster: do not inspect internal .unitypackage filenames')
    ap.add_argument('--max-entries', type=int, default=80000, help='Safety limit per archive')
    args = ap.parse_args()
    if args.max_entries < 1:
        ap.error('--max-entries must be positive')
    try:
        build(args.root, index_dir=args.index_dir,
              scan_unity=not args.skip_unity_contents, max_entries=args.max_entries)
    except (OSError, sqlite3.Error, ValueError) as ex:
        print(f'INDEX ERROR: {ex}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
