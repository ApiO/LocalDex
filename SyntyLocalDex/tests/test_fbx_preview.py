"""FBX static geometry and preview endpoints; self-contained synthetic mesh files."""
import io
import json
import shutil
import struct
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

from build_local_dex import build
from fbx_geometry import parse_fbx_geometry, thumbnail_svg, FBXPreviewError
from local_dex_server import LocalDexServer

ASCII_FBX = b'''FBXHeaderExtension: { FBXVersion: 7400 }
Objects: {
    Geometry: 1000, "Geometry::Triangle", "Mesh" {
        Vertices: *9 { a: 0,0,0, 50,0,0, 0,50,0 }
        PolygonVertexIndex: *3 { a: 0,1,-3 }
    }
}
'''


def binary_fbx(version=7400):
    def scalar(code, value):
        if code == 'S':
            b = value.encode('utf-8'); return b'S' + struct.pack('<I', len(b)) + b
        if code == 'L': return b'L' + struct.pack('<q', value)
        raise AssertionError(code)
    def array(code, items):
        fmt = '<' + str(len(items)) + ('d' if code == 'd' else 'i')
        raw = struct.pack(fmt, *items)
        compressed = zlib.compress(raw)
        return code.encode('ascii') + struct.pack('<III', len(items), 1, len(compressed)) + compressed
    def node(name, properties, children, start):
        h = 25 if version >= 7500 else 13
        begin_children = start + h + len(name) + len(properties)
        childbytes = b''
        for child in children:
            part = child(begin_children + len(childbytes))
            childbytes += part
        childbytes += bytes(h)
        end = begin_children + len(childbytes)
        fmt = '<QQQB' if version >= 7500 else '<IIIB'
        return struct.pack(fmt, end, 3 if name=='Geometry' else 1, len(properties), len(name)) + name.encode() + properties + childbytes
    def vertices(start): return node('Vertices', array('d',[0.,0.,0.,2.,0.,0.,0.,2.,0.]), [], start)
    def polygons(start): return node('PolygonVertexIndex', array('i',[0,1,-3]), [], start)
    def geometry(start):
        props = scalar('L',1) + scalar('S','Geometry::Triangle') + scalar('S','Mesh')
        return node('Geometry', props, [vertices, polygons], start)
    def objects(start): return node('Objects', scalar('L',0), [geometry], start)
    prefix = b'Kaydara FBX Binary  \x00\x1a\x00' + struct.pack('<I', version)
    return prefix + objects(len(prefix)) + bytes(25 if version >= 7500 else 13)


class TestFbxPreview(unittest.TestCase):
    def test_ascii_and_binary_geometry(self):
        for data in (ASCII_FBX, binary_fbx(7400), binary_fbx(7500)):
            mesh = parse_fbx_geometry(data)
            self.assertEqual(len(mesh['vertices']), 9)
            self.assertEqual(mesh['triangles'], [0,1,2])
            self.assertEqual(mesh['meshes'], 1)
            svg = thumbnail_svg(mesh)
            self.assertIn(b'<svg', svg)
            self.assertIn(b'<path', svg)
            self.assertNotIn(b'<script', svg)
        with self.assertRaises(FBXPreviewError):
            parse_fbx_geometry(b'invalid fbx content')

    def test_fbx_preview_from_loose_zip_and_unity(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            lib = base/'SyntyLibrary'
            lib.mkdir()
            pack = lib/'POLYGON - Test Pack'
            pack.mkdir()
            (pack/'loose.fbx').write_bytes(binary_fbx())
            with zipfile.ZipFile(pack/'models.zip','w') as zf:
                zf.writestr('Meshes/from_zip.fbx', ASCII_FBX)
            guid = 'aa'*16
            with tarfile.open(pack/'unity.unitypackage','w:gz') as tf:
                for member, raw in [(guid+'/pathname',b'Assets/Meshes/from_unity.fbx'),
                                    (guid+'/asset', binary_fbx())]:
                    info = tarfile.TarInfo(member)
                    info.size = len(raw)
                    tf.addfile(info, io.BytesIO(raw))
            dex = base/'SyntyLocalDex'/'.localdex'
            build(lib, index_dir=dex, verbose=False)
            server = LocalDexServer(('127.0.0.1', 0), lib, index_dir=dex)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(lambda: (server.shutdown(),server.server_close(),worker.join(timeout=5)))
            host = f'http://127.0.0.1:{server.server_port}'
            with urllib.request.urlopen(host + '/api/search?view=assets&q=fbx') as r:
                assets = json.load(r)['items']
            for name in ('loose.fbx','from_zip.fbx','from_unity.fbx'):
                a = next(x for x in assets if x['name'] == name)
                with urllib.request.urlopen(host + '/api/fbx-geometry/' + a['id']) as r:
                    self.assertEqual(r.status, 200)
                    model = json.load(r)
                    self.assertEqual(model['triangles'], [0,1,2])
                with urllib.request.urlopen(host + '/api/fbx-thumb/' + a['id']) as r:
                    self.assertIn('image/svg+xml',r.headers['Content-Type'])
                    self.assertIn(b'<svg',r.read())
                self.assertTrue(list((dex/'fbx_thumbs').glob(f'{a["id"]}*.svg')))
            self.assertFalse((lib/'.localdex').exists())
            with urllib.request.urlopen(host + '/fbx_viewer.js') as resp:
                self.assertIn('javascript', resp.headers['Content-Type'])
                self.assertIn(b'startFbxViewer', resp.read())
            with self.assertRaises(urllib.error.HTTPError) as ex:
                urllib.request.urlopen(host+'/api/fbx-geometry/'+'0'*24)
            self.assertEqual(ex.exception.code,404)
            with self.assertRaises(urllib.error.HTTPError) as ex:
                urllib.request.urlopen(host+'/api/fbx-thumb/bad')
            self.assertEqual(ex.exception.code,400)

    def test_card_markup_has_no_old_footer_or_name_rows(self):
        js = (Path(__file__).resolve().parents[1]/'local_dex_web'/'app.js').read_text('utf-8')
        self.assertNotIn('class="asset-footer"', js)
        self.assertNotIn('class="asset-card-name"', js)
        self.assertNotIn('class="asset-pack-name"', js)
        self.assertIn('asset-info-tooltip',js)
        self.assertIn('/api/fbx-thumb/',js)


if __name__ == '__main__': unittest.main()
