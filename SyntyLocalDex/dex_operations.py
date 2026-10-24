"""Local Dex's explicit, local-only installer / sync / index job controller.

No user-provided executable paths or shell commands are accepted. Downloader
configuration and library data are never modified by background jobs except as
explicitly requested via the downloader's own public CLI.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ACTIONS = ('install', 'downloads', 'assets')
MAX_LINES = 120


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class JobError(Exception):
    pass


class DexOperations:
    def __init__(self, dex_dir: Path, library: Path, index_dir: Path,
                 build_index: Callable, index_lock: threading.Lock):
        self.dex_dir = Path(dex_dir).resolve()
        self.downloader = self.dex_dir.parent / 'SyntyDownloader'
        self.library = Path(library).resolve()
        self.index_dir = Path(index_dir).resolve()
        self.build_index = build_index
        self.index_lock = index_lock
        self.lock = threading.RLock()
        self.active: str | None = None
        self.proc: subprocess.Popen | None = None
        self.input_stage: str | None = None
        self.partial = ''
        self.lines: deque[str] = deque(maxlen=MAX_LINES)
        self.history_path = self.index_dir / 'operations.json'
        self.history = {kind: self._empty() for kind in ACTIONS}
        if self.history_path.exists():
            try:
                data = json.loads(self.history_path.read_text(encoding='utf-8'))
                for kind in ACTIONS:
                    if isinstance(data.get(kind), dict):
                        self.history[kind].update({k: data[kind][k] for k in
                            ('state', 'started_at', 'finished_at', 'exit_code', 'message')
                            if k in data[kind]})
                for item in self.history.values():
                    if item['state'] in ('running', 'waiting_input'):
                        item['state'] = 'interrupted'
                        item['finished_at'] = now()
                        item['message'] = 'Local Dex stopped before this job completed.'
            except (ValueError, OSError, TypeError):
                pass
        self._ready_cache: tuple[float, dict] | None = None

    @staticmethod
    def _empty() -> dict:
        return {'state': 'never', 'started_at': None, 'finished_at': None,
                'exit_code': None, 'message': ''}

    @property
    def python(self) -> Path:
        return self.downloader / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')

    def _store(self) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        temp = self.history_path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(self.history, indent=2, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.history_path)

    def readiness(self, force: bool = False) -> dict:
        with self.lock:
            if not force and self._ready_cache and time.monotonic() - self._ready_cache[0] < 12:
                return dict(self._ready_cache[1])
        config = self.downloader / 'config.yaml'
        installer = self.downloader / 'install_synty_sync.ps1'
        script = self.downloader / 'synty_sync.py'
        data = {'downloader_found': script.is_file(), 'installer_found': installer.is_file(),
                'python_installed': self.python.is_file(), 'dependencies_ok': False,
                'chromium_installed': False, 'config_exists': config.is_file(),
                'credentials_configured': False,
                'config_valid': False, 'library_matches': False,
                'ready': False, 'error': '',
                'downloader_dir': str(self.downloader), 'config_path': str(config),
                'library_dir': str(self.library), 'configured_library': None}
        if data['python_installed'] and script.is_file():
            # No credentials are emitted. All paths are fixed sibling paths.
            check = '''import json,sys\nfrom pathlib import Path\nfrom playwright.sync_api import sync_playwright\nfrom synty_sync import load_config\nc=load_config(Path(sys.argv[1]))\nwith sync_playwright() as p:\n  browser=Path(p.chromium.executable_path).is_file()\nprint(json.dumps({'configured_library':str(c.output_dir),'chromium_installed':browser,'credentials_configured':('@' in c.email and c.email.strip().lower() != 'toto')}))'''
            try:
                proc = subprocess.run([str(self.python), '-c', check, str(config)],
                                      cwd=str(self.downloader), capture_output=True,
                                      text=True, errors='replace', timeout=12)
                if proc.returncode == 0:
                    value = json.loads(proc.stdout.strip().splitlines()[-1])
                    data['dependencies_ok'] = True
                    data['chromium_installed'] = bool(value['chromium_installed'])
                    data['config_valid'] = True
                    data['credentials_configured'] = bool(value['credentials_configured'])
                    data['configured_library'] = value['configured_library']
                    data['library_matches'] = Path(value['configured_library']).resolve() == self.library
                else:
                    # Configuration errors and missing modules are intentionally distinct.
                    try:
                        imports = subprocess.run([str(self.python), '-c',
                           'import bs4; import yaml; import playwright'], cwd=str(self.downloader),
                           capture_output=True, timeout=6)
                        data['dependencies_ok'] = imports.returncode == 0
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    data['error'] = ('Check config.yaml and installed Python modules.' if data['dependencies_ok']
                                     else 'Python dependencies missing or damaged.')
            except (OSError, ValueError, subprocess.TimeoutExpired, KeyError, IndexError):
                data['error'] = 'Unable to validate the local downloader.'
        if data['config_valid'] and not data['library_matches']:
            data['error'] = 'config.yaml output_dir differs from the SyntyLibrary used by Local Dex.'
        elif data['config_valid'] and not data['credentials_configured']:
            data['error'] = 'Set your real login.email in config.yaml (currently a placeholder). '
        elif data['config_valid'] and not data['chromium_installed']:
            data['error'] = 'Playwright Chromium is not installed.'
        elif not data['config_exists']:
            data['error'] = 'config.yaml is missing: copy config.example.yaml and configure your account.'
        data['ready'] = all(data[key] for key in ('downloader_found', 'python_installed',
            'dependencies_ok', 'chromium_installed', 'config_valid', 'credentials_configured', 'library_matches'))
        with self.lock:
            self._ready_cache = (time.monotonic(), data)
        return dict(data)

    def snapshot(self, force: bool = False) -> dict:
        with self.lock:
            return {'readiness': self.readiness(force=force), 'active': self.active,
                    'input_stage': self.input_stage, 'history':
                    {k: dict(v) for k, v in self.history.items()},
                    'log': list(self.lines)[-70:] if self.active else
                    list(self.lines)[-30:], 'partial': self.partial[-350:],
                    'observed': self.observed_activity()}

    def observed_activity(self) -> dict:
        # Observation is not proof that an external run completed successfully.
        result = {}
        for name, path in [('downloads', self.library / '.synty_sync.log'),
                           ('assets', self.index_dir / 'catalog.json')]:
            try:
                result[name] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec='seconds')
            except OSError:
                result[name] = None
        return result

    def start(self, action: str, headless: bool = False) -> None:
        if action not in ACTIONS:
            raise JobError('Unsupported operation')
        with self.lock:
            if self.active:
                raise JobError(f'Another operation is running: {self.active}')
            if action == 'downloads' and not self.readiness(force=True)['ready']:
                raise JobError('Downloader is not ready. Install dependencies and configure config.yaml first.')
            if action == 'install' and (not (self.downloader / 'install_synty_sync.ps1').is_file()
                                       or os.name != 'nt'):
                raise JobError('The downloader installer requires Windows and install_synty_sync.ps1.')
            if action == 'assets' and not self.library.is_dir():
                raise JobError('The SyntyLibrary folder is missing.')
            self.active = action
            self.input_stage = None
            self.lines.clear()
            self.partial = ''
            self.history[action] = {'state': 'running', 'started_at': now(),
                                    'finished_at': None, 'exit_code': None, 'message': ''}
            self._store()
        thread = threading.Thread(target=self._worker, args=(action, headless), daemon=True,
                                  name='localdex-' + action)
        thread.start()

    def _log(self, message: str) -> None:
        if message:
            with self.lock:
                self.lines.append(message[-900:])

    def _execute(self, args: list[str], cwd: Path, interactive: bool = False) -> int:
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if not interactive else 0
        proc = subprocess.Popen(args, cwd=str(cwd), stdin=subprocess.PIPE if interactive else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace', bufsize=1, creationflags=creationflags)
        with self.lock:
            self.proc = proc
        buffer = ''
        try:
            assert proc.stdout is not None
            while True:
                char = proc.stdout.read(1)
                if not char:
                    break
                if char == '\r':
                    continue
                buffer += char
                if len(buffer) > 4096:
                    self._log(buffer[:3500])
                    buffer = buffer[3500:]
                if char == '\n':
                    self._log(buffer.rstrip('\n'))
                    buffer = ''
                # Python input() prints a prompt without a newline. Detect it
                # from the actual downloader implementation, not arbitrary text.
                if interactive and self.input_stage is None:
                    stage = None
                    if 'Code reçu par e-mail (ou Entrée' in buffer and buffer.endswith(' : '):
                        stage = 'code'
                    elif 'Quand la connexion est terminée dans Chromium' in buffer and buffer.endswith('... '):
                        stage = 'confirm'
                    if stage:
                        with self.lock:
                            self.input_stage = stage
                            self.history['downloads']['state'] = 'waiting_input'
                with self.lock:
                    self.partial = buffer[-350:]
            if buffer.strip():
                self._log(buffer.strip())
            return proc.wait()
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stdin is not None:
                proc.stdin.close()
            with self.lock:
                self.proc = None
                self.input_stage = None
                self.partial = ''

    def reply(self, text: str) -> None:
        with self.lock:
            if self.active != 'downloads' or self.input_stage not in ('code', 'confirm'):
                raise JobError('No pending authentication prompt')
            if self.input_stage == 'confirm':
                text = ''
            elif text and (not text.isdigit() or len(text) > 12):
                raise JobError('The email code must be numeric (up to 12 digits)')
            proc = self.proc
            if not proc or not proc.stdin or proc.poll() is not None:
                raise JobError('Downloader is not accepting input')
            try:
                proc.stdin.write(text + '\n')
                proc.stdin.flush()
            except (OSError, BrokenPipeError) as exc:
                raise JobError('Downloader is no longer accepting input') from exc
            self.input_stage = None
            self.history['downloads']['state'] = 'running'

    def _worker(self, action: str, headless: bool) -> None:
        return_code = 1
        try:
            if action == 'assets':
                if not self.index_lock.acquire(blocking=False):
                    raise JobError('Index rebuild already running')
                try:
                    self._log('Rebuilding local catalog from the sibling SyntyLibrary folder...')
                    result = self.build_index(self.library, index_dir=self.index_dir,
                                              scan_unity=True, verbose=False)
                    self._log(f"Indexed {result['stats']['assets']} assets in {result['stats']['packs']} packs.")
                    return_code = 0
                finally:
                    self.index_lock.release()
            elif action == 'install':
                self._log('Installing Python dependencies and Playwright using the existing Windows installer...')
                return_code = self._execute(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                     '-File', str(self.downloader / 'install_synty_sync.ps1')], self.downloader)
            else:
                self._log('Starting download sync with stored configuration. Browser opens if headless is disabled.')
                argv = [str(self.python), '-u', str(self.downloader / 'synty_sync.py'),
                        '--config', str(self.downloader / 'config.yaml')]
                if headless:
                    argv.append('--headless')
                return_code = self._execute(argv, self.downloader, interactive=not headless)
            self._log('Operation completed.' if return_code == 0 else f'Process exited with code {return_code}.')
        except Exception as exc:
            # Do not include passwords, local config content, or secret code input.
            self._log(f'Operation failed: {type(exc).__name__}: {exc}')
        finally:
            with self.lock:
                self.history[action].update(state='success' if return_code == 0 else 'failed',
                    finished_at=now(), exit_code=return_code,
                    message='Completed successfully.' if return_code == 0 else 'See the operation log for details.')
                self.active = None
                self.proc = None
                self.input_stage = None
                self.partial = ''
                self._ready_cache = None
                self._store()

    def open_config(self) -> None:
        if os.name != 'nt':
            raise JobError('Open config.yaml with your local editor')
        file = self.downloader / 'config.yaml'
        if not file.exists():
            example = self.downloader / 'config.example.yaml'
            if not example.is_file():
                raise JobError('config.example.yaml not found')
            shutil.copy2(example, file)
        subprocess.Popen(['notepad.exe', str(file)])
        with self.lock:
            self._ready_cache = None
