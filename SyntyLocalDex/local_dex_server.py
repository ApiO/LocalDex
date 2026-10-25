#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Local-only web interface for the Synty Dex catalog. Standard-library server."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import struct
import sqlite3
import subprocess
import tarfile
import zipfile
from pathlib import PurePosixPath
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

from build_local_dex import (DEFAULT_LIBRARY, DEFAULT_INDEX_DIR, VIEWABLE_ASSETS_SQL,
                             build, connect_db)
from fbx_geometry import FBXPreviewError, MAX_FBX_BYTES, parse_fbx_geometry, thumbnail_svg
from dex_operations import DexOperations, JobError

WEB_DIR = Path(__file__).resolve().parent / 'local_dex_web'
MAX_BODY = 4096
# Media is served on demand to the loopback browser, never written into the library.
# Caps protect against very large archives, decompression bombs, and memory pressure.
PREVIEW_FORMATS = {
    '.png': ('image/png', 12_000_000),
    '.jpg': ('image/jpeg', 12_000_000),
    '.jpeg': ('image/jpeg', 12_000_000),
    '.webp': ('image/webp', 12_000_000),
    '.gif': ('image/gif', 12_000_000),
    '.mp3': ('audio/mpeg', 28_000_000),
    '.ogg': ('audio/ogg', 28_000_000),
    '.wav': ('audio/wav', 28_000_000),
    '.mp4': ('video/mp4', 32_000_000),
    '.webm': ('video/webm', 32_000_000),
    '.obj': ('text/plain; charset=utf-8', 3_000_000),
}


def reveal_file(path: Path) -> None:
    """Open the containing folder and, where supported, select the downloaded file."""
    if sys.platform == 'win32':
        subprocess.Popen(['explorer.exe', '/select,', str(path)])
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path.parent)])


class LocalDexHandler(BaseHTTPRequestHandler):
    server: LocalDexServer

    def log_message(self, fmt: str, *args) -> None:
        print('[localdex] ' + fmt % args)

    def respond(self, code: int, data: bytes, content_type: str, cache: str = 'no-store') -> None:
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', cache)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                         "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)

    def json_response(self, data: object, status: int = 200) -> None:
        self.respond(status, json.dumps(data, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

    def error_json(self, status: int, message: str) -> None:
        self.json_response({'error': message}, status)

    def is_local_request(self) -> bool:
        return self.client_address[0] in ('127.0.0.1', '::1')

    def load_manifest(self) -> dict:
        return json.loads((self.server.index_dir / 'catalog.json').read_text(encoding='utf-8'))

    def do_GET(self) -> None:
        if not self.is_local_request():
            return self.error_json(403, 'Localhost only')
        url = urlsplit(self.path)
        path = url.path
        try:
            if path == '/api/catalog':
                return self.json_response(self.load_manifest())
            if path == '/api/configuration':
                return self.json_response(self.server.operations.snapshot(force=parse_qs(url.query).get('refresh') == ['1']))
            if path == '/api/session':
                return self.json_response({'token': self.server.token})
            if path == '/api/search':
                return self.search(parse_qs(url.query))
            if path.startswith('/api/preview/'):
                return self.preview(path.removeprefix('/api/preview/'))
            if path.startswith('/api/fbx-geometry/'):
                return self.fbx_geometry(path.removeprefix('/api/fbx-geometry/'), thumbnail=False)
            if path.startswith('/api/fbx-thumb/'):
                return self.fbx_geometry(path.removeprefix('/api/fbx-thumb/'), thumbnail=True)
            if path.startswith('/api/cover/'):
                return self.cover(path.removeprefix('/api/cover/'))
            if path in ('/', '/index.html'):
                f = WEB_DIR / 'index.html'
                return self.respond(200, f.read_bytes(), 'text/html; charset=utf-8')
            if path in ('/styles.css', '/app.js', '/fbx_viewer.js'):
                f = WEB_DIR / path[1:]
                return self.respond(200, f.read_bytes(), 'text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8', 'no-cache')
            # Branding files are deliberately allowlisted; do not serve arbitrary local paths.
            brand_media = {
                '/logo.png': 'image/png',
                '/favicon.png': 'image/png',
                '/favicon.ico': 'image/x-icon',
            }
            if path in brand_media:
                f = WEB_DIR / path[1:]
                return self.respond(200, f.read_bytes(), brand_media[path], 'no-cache')
            return self.error_json(404, 'Not found')
        except (sqlite3.Error, OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as ex:
            return self.error_json(500, str(ex))

    def cover(self, filename: str) -> None:
        if not filename or '/' in filename or '\\' in filename or '..' in filename:
            return self.error_json(400, 'Invalid cover path')
        p = (self.server.index_dir / 'covers' / filename).resolve()
        if not p.is_relative_to((self.server.index_dir / 'covers').resolve()) or not p.is_file():
            return self.error_json(404, 'No cover image')
        mimetype = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        if mimetype not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp', 'image/avif'):
            return self.error_json(400, 'Invalid image type')
        if p.stat().st_size > 8_000_000:
            return self.error_json(413, 'Image too large')
        return self.respond(200, p.read_bytes(), mimetype, 'max-age=3600')

    def preview(self, asset_id: str) -> None:
        """Serve small, known-safe media from indexed local files or archive members.

        The database identifies the source and archive member. Arbitrary client paths
        are never accepted, and the original library is never changed.
        """
        if len(asset_id) != 24 or any(c not in '0123456789abcdef' for c in asset_id):
            return self.error_json(400, 'Invalid asset id')
        with closing(connect_db(self.server.index_dir / 'index.sqlite3')) as db:
            row = db.execute('SELECT source_rel,inner_path,ext,bytes FROM assets WHERE id=?',
                             (asset_id,)).fetchone()
        if not row:
            return self.error_json(404, 'Asset not found')
        ext = row['ext'].lower()
        if ext not in PREVIEW_FORMATS:
            return self.error_json(415, 'No browser preview for this format')
        mimetype, max_size = PREVIEW_FORMATS[ext]
        if row['bytes'] > max_size:
            return self.error_json(413, 'Preview exceeds size limit')
        source = (self.server.root / row['source_rel']).resolve()
        if not source.is_relative_to(self.server.root) or not source.is_file():
            return self.error_json(404, 'Source file missing')
        inner = row['inner_path']
        if not inner:
            if source.stat().st_size > max_size:
                return self.error_json(413, 'Preview exceeds size limit')
            content = source.read_bytes()
        elif source.suffix.lower() == '.zip':
            with zipfile.ZipFile(source) as archive:
                # Limit entry by its declared uncompressed size before reading it.
                try:
                    info = archive.getinfo(inner)
                except KeyError:
                    return self.error_json(404, 'Archive entry not found')
                if info.is_dir() or info.file_size > max_size:
                    return self.error_json(413, 'Preview exceeds size limit')
                with archive.open(info) as handle:
                    content = handle.read(max_size + 1)
        elif source.suffix.lower() == '.unitypackage':
            content = self.unity_preview(source, inner, max_size)
            if content is None:
                return self.error_json(404, 'Asset preview not found in Unity package')
        else:
            return self.error_json(415, 'Unsupported archive format')
        if len(content) > max_size:
            return self.error_json(413, 'Preview exceeds size limit')
        return self.respond(200, content, mimetype, 'private, max-age=300')

    @staticmethod
    def unity_preview(source: Path, pathname: str, max_size: int) -> bytes | None:
        """Resolve Unity's GUID/pathname and read the matching GUID/asset in memory.

        Only invoked when the user selects an indexed Unity image or media item.
        Tar member filenames never become filesystem paths.
        """
        with tarfile.open(source, 'r:gz') as archive:
            asset_members = {}
            target = None
            for entry in archive:
                if not entry.isfile():
                    continue
                guid, _, component = entry.name.partition('/')
                if component == 'asset' and entry.size <= max_size:
                    asset_members[guid] = entry
                elif component == 'pathname' and entry.size <= 2048:
                    handle = archive.extractfile(entry)
                    if handle and handle.read(2049).decode('utf-8', 'replace').strip() == pathname:
                        target = guid
                        if guid in asset_members:
                            break
            member = asset_members.get(target) if target else None
            if member is None:
                return None
            handle = archive.extractfile(member)
            return handle.read(max_size + 1) if handle else None

    def fbx_geometry(self, asset_id: str, thumbnail: bool = False) -> None:
        """Preview an indexed FBX (on-disk, ZIP or Unity tar.gz), without extraction.

        The browser receives only mesh coordinates, not raw FBX files, private
        material paths or embedded texture data. Thumbnail caching stays in Dex.
        """
        if len(asset_id) != 24 or any(c not in '0123456789abcdef' for c in asset_id):
            return self.error_json(400, 'Invalid asset id')
        with closing(connect_db(self.server.index_dir / 'index.sqlite3')) as db:
            row = db.execute('SELECT source_rel,inner_path,ext,bytes FROM assets WHERE id=?',
                             (asset_id,)).fetchone()
        if row is None:
            return self.error_json(404, 'Asset not found')
        if row['ext'].lower() != '.fbx':
            return self.error_json(415, 'Not an FBX file')
        if row['bytes'] is not None and row['bytes'] > MAX_FBX_BYTES:
            return self.error_json(413, 'FBX is too large for interactive preview')
        source = (self.server.root / row['source_rel']).resolve()
        if not source.is_relative_to(self.server.root) or not source.is_file():
            return self.error_json(404, 'Source file missing')

        # An asset ID alone is not a cache fingerprint: the underlying file might
        # have been replaced since indexing. Include the source mtime and size.
        stamp = source.stat()
        cache = self.server.index_dir / 'fbx_thumbs' / f'{asset_id}_{stamp.st_mtime_ns}_{stamp.st_size}.svg'
        if thumbnail and cache.exists():
            return self.respond(200, cache.read_bytes(), 'image/svg+xml', 'private, max-age=3600')
        try:
            inner = row['inner_path']
            if not inner:
                if source.stat().st_size > MAX_FBX_BYTES:
                    return self.error_json(413, 'FBX is too large for preview')
                content = source.read_bytes()
            elif source.suffix.lower() == '.zip':
                with zipfile.ZipFile(source) as archive:
                    info = archive.getinfo(inner)
                    if info.is_dir() or info.file_size > MAX_FBX_BYTES:
                        return self.error_json(413, 'FBX archive member is too large')
                    with archive.open(info) as handle:
                        content = handle.read(MAX_FBX_BYTES + 1)
            elif source.suffix.lower() == '.unitypackage':
                content = self.unity_preview(source, inner, MAX_FBX_BYTES)
                if content is None:
                    return self.error_json(404, 'FBX not present in Unity package')
            else:
                return self.error_json(415, 'Unsupported source archive')
            if len(content) > MAX_FBX_BYTES:
                return self.error_json(413, 'FBX uncompressed data exceeds safety limit')
            mesh = parse_fbx_geometry(content)
        except (FBXPreviewError, KeyError, struct.error) as exc:
            return self.error_json(422, f'FBX geometry preview unavailable: {exc}')
        if thumbnail:
            result = thumbnail_svg(mesh)
            # Write only to Dex's cache, never into the downloaded packages.
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(result)
            return self.respond(200, result, 'image/svg+xml', 'private, max-age=3600')
        return self.json_response(mesh)

    def search(self, query: dict) -> None:
        def first(key: str, default: str = '') -> str:
            return str(query.get(key, [default])[0])[:180]
        view = first('view', 'assets')
        if view not in ('assets', 'files'):
            return self.error_json(400, 'Invalid view')
        text = first('q').strip().lower()
        collection = first('collection')
        kind = first('kind')
        category = first('category')
        engine = first('engine')
        pack_id = first('pack')
        try:
            page = max(1, min(10000, int(first('page', '1'))))
            limit = max(1, min(100, int(first('limit', '48'))))
        except ValueError:
            return self.error_json(400, 'Invalid pagination')
        where = [VIEWABLE_ASSETS_SQL if view == 'assets' else "a.inner_path = ''"]
        args: list[object] = []
        for term in text.split()[:8]:
            # Escape SQL LIKE wildcards; text is always bound as a parameter.
            escaped = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where.append("a.search_text LIKE ? ESCAPE '\\'")
            args.append('%' + escaped + '%')
        if collection:
            where.append('p.collection = ?')
            args.append(collection)
        if kind:
            where.append('a.kind = ?')
            args.append(kind)
        if category:
            where.append('a.category = ?')
            args.append(category)
        if engine:
            where.append('a.engine = ?')
            args.append(engine)
        if pack_id:
            where.append('a.pack_id = ?')
            args.append(pack_id)
        condition = ' AND '.join(where)
        with closing(connect_db(self.server.index_dir / 'index.sqlite3')) as db:
            total = db.execute('SELECT COUNT(*) FROM assets a JOIN packs p ON p.id=a.pack_id WHERE ' + condition,
                               args).fetchone()[0]
            rows = [dict(row) for row in db.execute('''SELECT a.id,a.pack_id,p.name AS pack_name,
                 a.source_rel,a.inner_path,a.name,a.title,a.kind,a.category,a.engine,a.ext,a.bytes
                 FROM assets a JOIN packs p ON p.id=a.pack_id WHERE ''' + condition +
                 ' ORDER BY a.title COLLATE NOCASE,a.name COLLATE NOCASE LIMIT ? OFFSET ?',
                 args + [limit, (page - 1) * limit]).fetchall()]
        self.json_response({'total': total, 'page': page, 'limit': limit, 'items': rows})

    def do_POST(self) -> None:
        if not self.is_local_request():
            return self.error_json(403, 'Localhost only')
        # Prevent drive-by requests from unrelated websites; no CORS support.
        origin = self.headers.get('Origin', '')
        base = f'http://127.0.0.1:{self.server.server_port}'
        if origin != base or self.headers.get('X-Localdex-Token') != self.server.token:
            return self.error_json(403, 'Invalid origin or token')
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 0 or size > MAX_BODY:
                return self.error_json(413, 'Invalid request size')
            data = json.loads(self.rfile.read(size)) if size else {}
            path = urlsplit(self.path).path
            if path == '/api/configuration/start':
                action = data.get('action')
                if action not in ('install', 'downloads', 'assets'):
                    return self.error_json(400, 'Unknown operation')
                self.server.operations.start(action, headless=data.get('headless') is True)
                return self.json_response({'ok': True, 'action': action}, 202)
            if path == '/api/configuration/reply':
                reply = data.get('code', '')
                if not isinstance(reply, str) or len(reply) > 20:
                    return self.error_json(400, 'Invalid authentication input')
                self.server.operations.reply(reply)
                return self.json_response({'ok': True})
            if path == '/api/configuration/open-file':
                self.server.operations.open_config()
                return self.json_response({'ok': True})
            if path == '/api/reindex':
                if self.server.operations.active:
                    return self.error_json(409, 'Another operation is running')
                if not self.server.index_lock.acquire(blocking=False):
                    return self.error_json(409, 'Indexing already in progress')
                try:
                    output = build(self.server.root, index_dir=self.server.index_dir,
                                   scan_unity=bool(data.get('deep_unity', True)), verbose=False)
                    return self.json_response({'ok': True, 'stats': output['stats']})
                finally:
                    self.server.index_lock.release()
            if path == '/api/reveal':
                item_id = str(data.get('id', ''))
                if len(item_id) != 24:
                    return self.error_json(400, 'Invalid asset id')
                with closing(connect_db(self.server.index_dir / 'index.sqlite3')) as db:
                    row = db.execute('SELECT source_rel FROM assets WHERE id=?', (item_id,)).fetchone()
                if not row:
                    return self.error_json(404, 'Asset not found')
                candidate = (self.server.root / row['source_rel']).resolve()
                if not candidate.is_relative_to(self.server.root) or not candidate.is_file():
                    return self.error_json(404, 'Downloaded file not found')
                reveal_file(candidate)
                return self.json_response({'ok': True})
            if path == '/api/reveal-pack':
                pack_id = str(data.get('id', ''))
                with closing(connect_db(self.server.index_dir / 'index.sqlite3')) as db:
                    row = db.execute('SELECT folder FROM packs WHERE id=?', (pack_id,)).fetchone()
                if not row:
                    return self.error_json(404, 'Pack not found')
                folder = (self.server.root / row['folder']).resolve()
                if not folder.is_relative_to(self.server.root) or not folder.is_dir():
                    return self.error_json(404, 'Pack folder missing')
                if sys.platform == 'win32':
                    subprocess.Popen(['explorer.exe', str(folder)])
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', str(folder)])
                else:
                    subprocess.Popen(['xdg-open', str(folder)])
                return self.json_response({'ok': True})
            return self.error_json(404, 'Not found')
        except JobError as ex:
            return self.error_json(409, str(ex))
        except (ValueError, KeyError, OSError, sqlite3.Error, json.JSONDecodeError) as ex:
            return self.error_json(500, str(ex))


class LocalDexServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str,int], root: Path, index_dir: Path | None = None):
        super().__init__(address, LocalDexHandler)
        self.root = Path(root).expanduser().resolve()
        self.index_dir = (Path(index_dir) if index_dir is not None else DEFAULT_INDEX_DIR).expanduser().resolve()
        self.token = secrets.token_urlsafe(32)
        self.index_lock = threading.Lock()
        self.operations = DexOperations(WEB_DIR.parent, self.root, self.index_dir, build, self.index_lock)


def main() -> int:
    parser = argparse.ArgumentParser(description='Browse your downloaded Synty files locally')
    parser.add_argument('--root', '--output', type=Path, default=DEFAULT_LIBRARY,
                        help='Library directory (default: sibling ../SyntyLibrary)')
    parser.add_argument('--index-dir', type=Path, default=DEFAULT_INDEX_DIR,
                        help='Generated data directory (default: this Dex folder/.localdex)')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-open', action='store_true', help='Do not automatically open the web browser')
    parser.add_argument('--skip-unity-contents', action='store_true')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        if root == DEFAULT_LIBRARY.resolve() and not root.exists():
            # A fresh checkout can open Configuration before the first download.
            root.mkdir(parents=True, exist_ok=True)
        else:
            print(f'Library not found: {root}', file=sys.stderr)
            return 1
    index_dir = args.index_dir.expanduser().resolve()
    if index_dir == root or index_dir.is_relative_to(root):
        print('Index folder must be outside SyntyLibrary', file=sys.stderr)
        return 1
    if not (index_dir / 'catalog.json').exists() or not (index_dir / 'index.sqlite3').exists():
        print('First run: building your library index...')
        build(root, index_dir=index_dir, scan_unity=not args.skip_unity_contents)
    try:
        server = LocalDexServer(('127.0.0.1', args.port), root, index_dir=index_dir)
    except OSError as ex:
        print(f'Cannot bind local web server to port {args.port}: {ex}', file=sys.stderr)
        return 1
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'\nLocal Dex is running at {url}')
    print(f'Library folder: {root}')
    print(f'Index folder: {index_dir}')
    print('Press Ctrl+C to stop. The server is reachable only from this computer.\n')
    if not args.no_open:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print('\nStopping Local Dex...')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
