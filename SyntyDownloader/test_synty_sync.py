"""Run: python -m unittest test_synty_sync.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

import synty_sync as module


class ConfigTests(unittest.TestCase):
    def test_default_config_is_relative_to_script_not_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            downloader = root / 'SyntyDownloader'
            downloader.mkdir()
            yml = downloader / 'config.yaml'
            yml.write_text('''output_dir: ../SyntyLibrary
login:
  email: account@example.com
  password: a-secret
  customer_id: "123456789"
''', encoding='utf-8')
            config = module.load_config(yml)
            self.assertEqual(config.output_dir, root / 'SyntyLibrary')
            self.assertEqual(config.email, 'account@example.com')
            self.assertEqual(config.password, 'a-secret')
            self.assertIn('/orders/123456789?', config.library_url)

            # CLI config validation works from a different current directory.
            script = Path(module.__file__).resolve()
            result = subprocess.run([sys.executable, str(script), '--config', str(yml),
                                     '--check-config'], cwd=str(root),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(root / 'SyntyLibrary'), result.stdout)
            self.assertNotIn('a-secret', result.stdout + result.stderr)
            self.assertFalse((root / 'SyntyLibrary').exists())

    def test_validation(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'config.yaml'
            f.write_text('login: {}\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'output_dir'):
                module.load_config(f)
            f.write_text('output_dir: ../SyntyLibrary\nlogin:\n  email: user@example.com\n  password: 123\n  customer_id: abc\n')
            with self.assertRaisesRegex(ValueError, 'login.password'):
                module.load_config(f)
            f.write_text('output_dir: ../SyntyLibrary\nlogin:\n  email: user@example.com\n  password: ""\n  customer_id: abc\n')
            with self.assertRaisesRegex(ValueError, 'login.customer_id'):
                module.load_config(f)
            with self.assertRaises(FileNotFoundError):
                module.load_config(Path(d) / 'not_found.yaml')

    def test_html_library_pagination_with_customer_id_from_url(self):
        html_path = Path(__file__).parent.parent.parent / 'Synty Store - my download.html'
        if not html_path.exists():
            self.skipTest('Reference HTML file not included in repository')
        url = 'https://syntystore.com/apps/downloads/orders/4393663955098?line_items_page=1'
        packages, next_url = module.parse_library(html_path.read_text(encoding='utf-8'), url)
        self.assertEqual(len(packages), 15)
        self.assertEqual(packages[0].name, 'ANIMATION - Base Locomotion')
        self.assertIn('line_items_page=2', next_url)

    def test_file_buttons(self):
        html = '''<a class="button sky-pilot-button" href="/apps/downloads/downloads/123?email=a%40example.com">A</a>'''
        links = module.parse_file_links(html, 'https://syntystore.com/apps/downloads/orders/1')
        self.assertEqual(len(links), 1)
        self.assertEqual(module.download_id(links[0].url), '123')

    def test_history_without_deleting_existing_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            h = module.load_history(root / '.synty_history.json')
            testfile = root / 'pack' / 'file.zip'
            testfile.parent.mkdir()
            testfile.write_bytes(b'bytes')
            h['downloads']['abc'] = {'relative_path': 'pack/file.zip'}
            module.save_history(root / '.synty_history.json', h)
            self.assertTrue(module.history_path_exists(root, module.load_history(root / '.synty_history.json')['downloads']['abc']))
            self.assertEqual(testfile.read_bytes(), b'bytes')


if __name__ == '__main__':
    unittest.main()
