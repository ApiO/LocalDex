"""Local Dex configuration APIs & interaction tests. No real account required."""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from build_local_dex import build
from local_dex_server import LocalDexServer
from dex_operations import DexOperations, JobError


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        parent = Path(self.tmp.name)
        self.library = parent / 'SyntyLibrary'
        pack = self.library / 'POLYGON - Simple Pack'
        pack.mkdir(parents=True)
        (pack / 'test.obj').write_text('v 0 0 0\nv 1 0 0\n')
        self.index_dir = parent / 'SyntyLocalDex' / '.localdex'
        build(self.library, index_dir=self.index_dir, verbose=False)
        self.srv = LocalDexServer(('127.0.0.1', 0), self.library, self.index_dir)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.base = f'http://127.0.0.1:{self.srv.server_port}'

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=3)

    def post(self, path, obj, token=None, origin=None):
        request = urllib.request.Request(self.base + path,
             data=json.dumps(obj).encode(), method='POST', headers={
                 'Origin': origin if origin is not None else self.base,
                 'Content-Type': 'application/json',
                 'X-Localdex-Token': token if token is not None else self.srv.token})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)

    def test_readiness_missing_downloader_does_not_disclose_secrets(self):
        with urllib.request.urlopen(self.base + '/api/configuration') as response:
            status = json.load(response)
        self.assertFalse(status['readiness']['ready'])
        self.assertTrue(status['readiness']['downloader_found'])
        self.assertFalse(status['readiness']['python_installed'])
        self.assertEqual(status['history']['install']['state'], 'never')
        self.assertIsNone(status['observed']['downloads'])
        self.assertIsNotNone(status['observed']['assets'])
        self.assertNotIn('password', json.dumps(status))

    def test_start_requires_csrf_token_and_fixed_action(self):
        for token, origin in [('bad', self.base), (self.srv.token, 'https://untrusted.example')]:
            with self.assertRaises(urllib.error.HTTPError) as ex:
                self.post('/api/configuration/start', {'action': 'assets'}, token, origin)
            self.assertEqual(ex.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as ex:
            self.post('/api/configuration/start', {'action': 'arbitrary-command'})
        self.assertEqual(ex.exception.code, 400)

    def test_asset_sync_is_background_tracks_last_run_and_blocks_conflicts(self):
        began = threading.Event()
        finished = threading.Event()
        original = self.srv.operations.build_index
        def slow_build(*args, **kwargs):
            began.set()
            if not finished.wait(6):
                raise TimeoutError('Test did not release indexer')
            return original(*args, **kwargs)
        self.srv.operations.build_index = slow_build
        code, response = self.post('/api/configuration/start', {'action': 'assets'})
        self.assertEqual(code, 202)
        self.assertTrue(began.wait(3))
        with self.assertRaises(urllib.error.HTTPError) as ex:
            self.post('/api/configuration/start', {'action': 'assets'})
        self.assertEqual(ex.exception.code, 409)
        with self.assertRaises(urllib.error.HTTPError) as ex:
            self.post('/api/reindex', {})
        self.assertEqual(ex.exception.code, 409)
        finished.set()
        for _ in range(100):
            if not self.srv.operations.active:
                break
            time.sleep(.04)
        self.assertIsNone(self.srv.operations.active)
        status = self.srv.operations.snapshot()
        self.assertEqual(status['history']['assets']['state'], 'success')
        self.assertTrue(status['history']['assets']['started_at'])
        self.assertTrue(status['history']['assets']['finished_at'])
        self.assertTrue((self.index_dir / 'operations.json').exists())
        reloaded = DexOperations(self.index_dir.parent, self.library, self.index_dir,
                                 build, threading.Lock())
        self.assertEqual(reloaded.history['assets']['state'], 'success')

    def test_realtime_2fa_prompt_and_browser_confirmation(self):
        script = self.index_dir.parent / 'mock_login.py'
        script.write_text('code=input("Code reçu par e-mail (ou Entrée pour le saisir dans le navigateur) : ")\n'
                          'input("Quand la connexion est terminée dans Chromium, appuyez sur Entrée ici... ")\n'
                          'print("Authenticated", flush=True)\n', encoding='utf-8')
        ops = self.srv.operations
        ops.active = 'downloads'
        result = {}
        t = threading.Thread(target=lambda: result.update(code=ops._execute(
            [sys.executable, '-u', str(script)], script.parent, interactive=True)))
        t.start()
        def stage(expected):
            for _ in range(160):
                if ops.input_stage == expected:
                    return
                time.sleep(.025)
            self.fail(f'Expected prompt {expected}, got {ops.input_stage}: {ops.partial!r}')
        try:
            stage('code')
            ops.reply('123456')
            stage('confirm')
            ops.reply('')
            t.join(timeout=5)
            self.assertFalse(t.is_alive())
            self.assertEqual(result['code'], 0)
            self.assertTrue(any('Authenticated' in x for x in ops.lines))
            self.assertNotIn('123456', '\n'.join(ops.lines))
        finally:
            if ops.proc and ops.proc.poll() is None:
                ops.proc.kill()
            t.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
