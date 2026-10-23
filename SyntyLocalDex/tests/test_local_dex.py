"""End-to-end local fixtures and API tests; no Synty account or internet needed."""
import io
import base64
import json
import shutil
import subprocess
import sys
import sqlite3
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

from build_local_dex import build
from local_dex_server import LocalDexServer


def make_fixture(root: Path):
    pack=root/'POLYGON - Adventure Pack'
    pack.mkdir(parents=True)
    with zipfile.ZipFile(pack/'POLYGON_Adventure_SourceFiles_v1.zip','w') as zf:
        zf.writestr('Models/Characters/Elf_Warrior.fbx', b'model')
        zf.writestr('Models/Props/Barrel_01.obj', b'prop')
        zf.writestr('Textures/Wood_Albedo.png', b'fake image')
        zf.writestr('../escape.fbx', b'bad path should be ignored')
        zf.writestr('Materials/Elf_Warrior.fbx.meta', b'meta')
        zf.writestr('pack_cover.png', b'fake local cover')
    # A genuine tar.gz layout containing the UnityPackage original path.
    with tarfile.open(pack/'POLYGON_Adventure_Unity_2021.unitypackage','w:gz') as tf:
        for guid, pathname in [('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','Assets/PolygonAdventure/Prefabs/Characters/Warrior.prefab'),
                               ('bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','Assets/PolygonAdventure/Models/Buildings/Tower.fbx')]:
            content=pathname.encode()
            info=tarfile.TarInfo(guid+'/pathname')
            info.size=len(content)
            tf.addfile(info,io.BytesIO(content))
    pack2=root/'ANIMATION - Bow Combat'
    pack2.mkdir()
    with zipfile.ZipFile(pack2/'ANIMATION_Bow_SourceFiles_v2.zip','w') as zf:
        zf.writestr('Animations/Attack_Bow.fbx', b'animation')
    (pack2/'readme.txt').write_text('Sample local test')
    (pack2/'Animations').mkdir()
    (pack2/'Animations'/'Dodge.fbx').write_bytes(b'loose model')
    (root/'.synty_history.json').write_text('{"secret":"should not appear in catalog"}')
    (root/'.synty_browser_profile').mkdir()
    (root/'.synty_browser_profile'/'cookies').write_text('hidden')

class TestLocalDex(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.root = self.parent / 'SyntyLibrary'
        self.root.mkdir()
        self.dex = self.parent / 'SyntyLocalDex'
        self.dex.mkdir()
        self.index_dir = self.dex / '.localdex'
        make_fixture(self.root)

    def test_build_and_incremental_scan(self):
        one=build(self.root, index_dir=self.index_dir, verbose=False)
        self.assertEqual(one['stats']['packs'],2)
        self.assertEqual(one['stats']['assets'],8) # 4 ZIP entries, 2 Unity paths, 1 archive animation, 1 loose animation
        self.assertNotIn('should not appear',json.dumps(one))
        self.assertNotIn('cookies',json.dumps(one))
        self.assertEqual(one['stats']['scanned_sources'],5)  # zip+unity, zip+readme+loose model
        two=build(self.root,index_dir=self.index_dir,verbose=False)
        self.assertEqual(two['stats']['scanned_sources'],0)
        self.assertEqual(two['stats']['cached_sources'],5)
        with sqlite3.connect(self.index_dir/'index.sqlite3') as db:
            text='\n'.join(row[0] for row in db.execute('SELECT name FROM assets'))
        self.assertIn('Warrior.prefab',text)
        self.assertIn('Dodge.fbx',text)
        self.assertIn('Elf_Warrior.fbx',text)
        self.assertNotIn('escape.fbx',text)

    def test_sibling_layout_read_only_and_relocatable(self):
        result = build(self.root, index_dir=self.index_dir, verbose=False)
        self.assertFalse((self.root / '.localdex').exists())
        self.assertTrue((self.index_dir / 'index.sqlite3').exists())
        self.assertTrue((self.index_dir / 'catalog.json').exists())
        self.assertEqual(result['library'].replace('\\', '/'), '../SyntyLibrary')
        self.assertNotIn(str(self.parent), json.dumps(result))
        with self.assertRaises(ValueError):
            build(self.root, index_dir=self.root / '.localdex', verbose=False)

    def test_cli_defaults_resolve_neighbor_from_script_not_cwd(self):
        src = Path(__file__).resolve().parents[1] / 'build_local_dex.py'
        shutil.copy2(src, self.dex / 'build_local_dex.py')
        proc = subprocess.run([sys.executable, str(self.dex / 'build_local_dex.py')],
                              cwd=self.parent, capture_output=True, text=True, timeout=40)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((self.index_dir / 'index.sqlite3').exists())
        self.assertFalse((self.root / '.localdex').exists())

    def test_previews_inside_zip_unity_and_loose_files(self):
        # Small genuine image plus an OBJ, served from the original source without extraction.
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==')
        pack = self.root / 'POLYGON - Adventure Pack'
        with zipfile.ZipFile(pack/'preview_test.zip', 'w') as archive:
            archive.writestr('Textures/Preview.png', png)
            archive.writestr('Models/Test.obj', b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
        (pack/'animated.gif').write_bytes(b'GIF89a' + b'\x00' * 20)
        with tarfile.open(pack/'preview.unitypackage', 'w:gz') as archive:
            guid = 'cccccccccccccccccccccccccccccccc'
            for name, content in [(guid+'/pathname', b'Assets/Images/MyPreview.png'), (guid+'/asset', png)]:
                info = tarfile.TarInfo(name); info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        build(self.root, index_dir=self.index_dir, verbose=False)
        srv = LocalDexServer(('127.0.0.1', 0), self.root, index_dir=self.index_dir)
        thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), thread.join(timeout=5)))
        base = f'http://127.0.0.1:{srv.server_port}'
        def search(q):
            return json.load(urllib.request.urlopen(base + '/api/search?view=assets&q=' + q))['items']
        for name, expected_type, expected_bytes in [
            ('Preview.png', 'image/png', png),
            ('MyPreview.png', 'image/png', png),
            ('animated.gif', 'image/gif', b'GIF89a' + b'\x00' * 20),
            ('Test.obj', 'text/plain', b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'),
        ]:
            entry = next(a for a in search(name) if a['name'] == name)
            with urllib.request.urlopen(base + '/api/preview/' + entry['id']) as response:
                self.assertIn(expected_type, response.headers['Content-Type'])
                self.assertEqual(response.read(), expected_bytes)
        # FBX is deliberately not served as untrusted browser media.
        fbx = next(a for a in search('Elf_Warrior') if a['name'] == 'Elf_Warrior.fbx')
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + '/api/preview/' + fbx['id'])
        self.assertEqual(err.exception.code, 415)
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + '/api/preview/../etc/passwd')
        self.assertEqual(err.exception.code, 400)

    def test_pack_cover_prefers_first_root_level_image_and_refreshes(self):
        pack = self.root / 'POLYGON - Adventure Pack'
        # Existing ZIP artwork is initially the fallback, because there are no
        # immediate JPG/PNG/GIF/etc. children of the package folder.
        initial = build(self.root, index_dir=self.index_dir, verbose=False)
        pack_id = next(p['id'] for p in initial['packs'] if p['name'] == pack.name)
        original_cover = next(p['cover'] for p in initial['packs'] if p['id'] == pack_id)
        self.assertTrue(original_cover)
        self.assertNotIn('-root-', original_cover)

        nested = pack / 'Graphics'
        nested.mkdir()
        (nested / '000-image.jpg').write_bytes(b'nested image ignored as root cover')
        (pack / 'Zebra.png').write_bytes(b'ZEBRA_IMAGE')
        (pack / 'album.jpg').write_bytes(b'ALBUM_IMAGE')
        first = build(self.root, index_dir=self.index_dir, verbose=False)
        image_cover = next(p['cover'] for p in first['packs'] if p['id'] == pack_id)
        self.assertIn('-root-', image_cover)
        self.assertEqual((self.index_dir / image_cover).read_bytes(), b'ALBUM_IMAGE')

        # Editing the same image must produce a new cover URL, since browsers
        # cache cover responses for an hour.
        source = pack / 'album.jpg'
        source.write_bytes(b'UPDATED_ALBUM_IMAGE')
        edited = build(self.root, index_dir=self.index_dir, verbose=False)
        updated_cover = next(p['cover'] for p in edited['packs'] if p['id'] == pack_id)
        self.assertNotEqual(updated_cover, image_cover)
        self.assertEqual((self.index_dir / updated_cover).read_bytes(), b'UPDATED_ALBUM_IMAGE')

        # A newly introduced, alphabetically earlier image must take precedence
        # even if the previous cover cache exists and all archives are unchanged.
        (pack / '01-intro.gif').write_bytes(b'GIF89a' + b'X' * 12)
        second = build(self.root, index_dir=self.index_dir, verbose=False)
        gif_cover = next(p['cover'] for p in second['packs'] if p['id'] == pack_id)
        self.assertEqual((self.index_dir / gif_cover).read_bytes(), b'GIF89a' + b'X' * 12)
        self.assertTrue(gif_cover.endswith('.gif'))

        srv = LocalDexServer(('127.0.0.1', 0), self.root, index_dir=self.index_dir)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), thread.join(timeout=5)))
        with urllib.request.urlopen(f'http://127.0.0.1:{srv.server_port}/api/cover/{Path(gif_cover).name}') as response:
            self.assertEqual(response.headers['Content-Type'], 'image/gif')
            self.assertEqual(response.read(), b'GIF89a' + b'X' * 12)

        # Removing images only changes the generated catalog; the library index
        # chooses the next eligible root image and finally falls back to artwork.
        (pack / '01-intro.gif').unlink()
        third = build(self.root, index_dir=self.index_dir, verbose=False)
        self.assertEqual(next(p['cover'] for p in third['packs'] if p['id'] == pack_id), updated_cover)
        (pack / 'album.jpg').unlink()
        (pack / 'Zebra.png').unlink()
        final = build(self.root, index_dir=self.index_dir, verbose=False)
        self.assertEqual(next(p['cover'] for p in final['packs'] if p['id'] == pack_id), original_cover)

    def test_first_root_cover_skips_oversized_images(self):
        pack = self.root / 'ANIMATION - Bow Combat'
        with (pack / 'AAA-too-large.png').open('wb') as f:
            f.truncate(8_000_001)
        (pack / 'BBB-selected.webp').write_bytes(b'WEBP_PLACEHOLDER')
        result = build(self.root, index_dir=self.index_dir, verbose=False)
        pack_info = next(p for p in result['packs'] if p['name'] == pack.name)
        self.assertEqual((self.index_dir / pack_info['cover']).read_bytes(), b'WEBP_PLACEHOLDER')
        self.assertTrue(pack_info['cover'].endswith('.webp'))

    def test_skip_unity_then_restore(self):
        a=build(self.root,index_dir=self.index_dir,scan_unity=False,verbose=False)
        b=build(self.root,index_dir=self.index_dir,scan_unity=True,verbose=False)
        self.assertEqual(b['stats']['scanned_sources'],1)
        self.assertGreater(b['stats']['assets'],a['stats']['assets'])

    def test_api_search_and_security(self):
        build(self.root,index_dir=self.index_dir,verbose=False)
        srv=LocalDexServer(('127.0.0.1',0),self.root,index_dir=self.index_dir)
        t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
        self.addCleanup(lambda:(srv.shutdown(),srv.server_close(),t.join(timeout=5)))
        base=f'http://127.0.0.1:{srv.server_port}'
        def fetch(path):
            return json.load(urllib.request.urlopen(base+path))
        data=fetch('/api/search?view=assets&q=Warrior')
        self.assertEqual(data['total'],2)
        self.assertTrue(any(x['name']=='Warrior.prefab' for x in data['items']))
        category=fetch('/api/search?view=assets&category=Character')
        self.assertGreaterEqual(category['total'],2)
        files=fetch('/api/search?view=files&q=SourceFiles')
        self.assertEqual(files['total'],2)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(base+'/api/reindex',data=b'{}',method='POST'))
        self.assertEqual(e.exception.code,403)
        session=fetch('/api/session')
        with patch('local_dex_server.reveal_file') as reveal:
            req=urllib.request.Request(base+'/api/reveal',data=json.dumps({'id':data['items'][0]['id']}).encode(),method='POST',headers={'Origin':base,'X-Localdex-Token':session['token'],'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as result: self.assertEqual(result.status,200)
            self.assertTrue(reveal.called)
        req=urllib.request.Request(base+'/api/reindex',data=b'{"deep_unity":true}',method='POST',headers={'Origin':base,'X-Localdex-Token':session['token'],'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as result:
            self.assertEqual(result.status,200)
            self.assertTrue(json.load(result)['ok'])

if __name__=='__main__':unittest.main()
