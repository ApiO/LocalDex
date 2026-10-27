#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Apply the Extra Tools / archive extraction UI patch to the current LocalDex checkout.

Run from any working directory after extracting the update ZIP into the repository root:
    py -3 tools/apply_archive_extraction_patch.py
The script validates all expected anchors before writing any source files.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PatchError(RuntimeError):
    pass


def replace_once(label: str, text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f'{label}: expected one patch anchor, found {count}. No project files were changed.')
    return text.replace(old, new, 1)


def patch_server(text: str) -> str:
    text = replace_once(
        'local_dex_server.py imports', text,
        'from dex_operations import DexOperations, JobError\n',
        'from dex_operations import DexOperations, JobError\n'
        'from archive_extractor import list_archives, extract_selected_archives\n')
    text = replace_once('local_dex_server.py request size limit', text,
                        'MAX_BODY = 4096\n', 'MAX_BODY = 65536\n')
    text = replace_once(
        'local_dex_server.py GET route', text,
        "            if path == '/api/configuration':\n",
        "            if path == '/api/archives':\n"
        "                return self.json_response({'archives': list_archives(self.server.root)})\n"
        "            if path == '/api/configuration':\n")
    extraction_route = '''            if path == '/api/extract-archives':
                selected = data.get('ids')
                if (not isinstance(selected, list) or not selected or len(selected) > 1000
                        or any(not isinstance(item, str) or len(item) != 24
                               or any(char not in '0123456789abcdef' for char in item)
                               for item in selected)):
                    return self.error_json(400, 'Select between 1 and 1000 valid archive IDs.')
                # Serialize archive extraction against downloads, installation and indexing.
                with self.server.operations.lock:
                    if self.server.operations.active:
                        return self.error_json(409, 'Another Local Dex operation is running.')
                    if not self.server.archive_lock.acquire(blocking=False):
                        return self.error_json(409, 'Archive extraction is already running.')
                    if not self.server.index_lock.acquire(blocking=False):
                        self.server.archive_lock.release()
                        return self.error_json(409, 'Indexing is already running.')
                try:
                    with self.server.operations.lock:
                        if self.server.operations.active:
                            return self.error_json(409, 'Another Local Dex operation is running.')
                    result = extract_selected_archives(self.server.root, selected)
                    return self.json_response(result)
                finally:
                    self.server.index_lock.release()
                    self.server.archive_lock.release()
            if path == '/api/configuration/start':
'''
    text = replace_once('local_dex_server.py extraction POST route', text,
                        "            if path == '/api/configuration/start':\n", extraction_route)
    text = replace_once(
        'local_dex_server.py configuration job guard', text,
        "                self.server.operations.start(action, headless=data.get('headless') is True)\n",
        "                with self.server.operations.lock:\n"
        "                    if self.server.archive_lock.locked():\n"
        "                        return self.error_json(409, 'Archive extraction is running.')\n"
        "                    self.server.operations.start(action, headless=data.get('headless') is True)\n")
    text = replace_once(
        'local_dex_server.py archive lock', text,
        '        self.index_lock = threading.Lock()\n'
        '        self.operations = DexOperations(WEB_DIR.parent, self.root, self.index_dir, build, self.index_lock)\n',
        '        self.index_lock = threading.Lock()\n'
        '        self.archive_lock = threading.Lock()\n'
        '        self.operations = DexOperations(WEB_DIR.parent, self.root, self.index_dir, build, self.index_lock)\n')
    return text


def patch_html(text: str) -> str:
    text = replace_once(
        'index.html navigation', text,
        '      <button class="nav-link" data-page="statistics"><span class="nav-icon">▥</span> Statistics</button>\n'
        '      <button class="nav-link" data-page="configuration"><span class="nav-icon">⚙</span> Configuration</button>\n',
        '      <button class="nav-link" data-page="statistics"><span class="nav-icon">▥</span> Statistics</button>\n'
        '      <button class="nav-link" data-page="extra-tools"><span class="nav-icon">⚒</span> Extra tools</button>\n'
        '      <button class="nav-link" data-page="configuration"><span class="nav-icon">⚙</span> Configuration</button>\n')
    extra_page = '''      <section id="extra-tools-view" class="extra-tools-view" hidden aria-label="Extra tools">
        <div class="section-top extra-tools-heading">
          <div><div class="eyebrow">LOCAL UTILITIES</div><h2>Extra tools</h2>
            <p>Extract downloaded package archives into folders beside the original files.</p></div>
          <button type="button" class="btn btn-outline" id="archives-refresh">Refresh archive list</button>
        </div>
        <div class="archive-selection-bar">
          <label class="archive-select-all"><input type="checkbox" id="archives-select-all"> Select all available</label>
          <span id="archive-count" class="archive-summary-count">— archives</span>
          <span id="archive-selection-count" class="archive-selection-count">0 selected</span>
          <button type="button" class="btn btn-primary" id="extract-archives" disabled>Extract archives</button>
        </div>
        <p id="archive-operation-status" class="archive-operation-status" role="status" aria-live="polite">
          Original archives are preserved. Existing extraction folders are skipped and never overwritten.
        </p>
        <div id="archive-operation-details" class="archive-operation-details" hidden></div>
        <div id="archive-list" class="archive-list" aria-live="polite">
          <div class="loading">Archive list will appear here.</div>
        </div>
      </section>
      <section id="configuration-view" class="configuration-view" hidden aria-label="Local Dex configuration">
'''
    text = replace_once(
        'index.html Extra tools page', text,
        '      <section id="configuration-view" class="configuration-view" hidden aria-label="Local Dex configuration">\n',
        extra_page)
    return text


def patch_js(text: str) -> str:
    text = replace_once(
        'app.js archive state', text,
        "let packViewMode = 'grid';\n",
        "let packViewMode = 'grid';\n"
        "let archiveItems = [];\n"
        "const selectedArchiveIds = new Set();\n"
        "let archiveListBusy = false;\n"
        "let archiveExtractionBusy = false;\n")
    text = replace_once(
        'app.js page flags', text,
        "  const isConfiguration = page === 'configuration';\n"
        "  const showDetails = page === 'assets' || isPack;\n",
        "  const isConfiguration = page === 'configuration';\n"
        "  const isExtraTools = page === 'extra-tools';\n"
        "  const showDetails = page === 'assets' || isPack;\n")
    text = replace_once(
        'app.js page visibility', text,
        "  if (isStatistics || isConfiguration) ++requestId;\n"
        "  $('statistics-view').hidden = !isStatistics;\n"
        "  $('configuration-view').hidden = !isConfiguration;\n"
        "  $('browse-view').hidden = isStatistics || isConfiguration;\n",
        "  if (isStatistics || isConfiguration || isExtraTools) ++requestId;\n"
        "  $('statistics-view').hidden = !isStatistics;\n"
        "  $('configuration-view').hidden = !isConfiguration;\n"
        "  $('extra-tools-view').hidden = !isExtraTools;\n"
        "  $('browse-view').hidden = isStatistics || isConfiguration || isExtraTools;\n")
    text = replace_once(
        'app.js page refresh dispatch', text,
        "  if (isConfiguration) refreshConfiguration();\n"
        "  else if (!isStatistics) refresh();\n",
        "  if (isConfiguration) refreshConfiguration();\n"
        "  else if (isExtraTools) refreshArchiveList();\n"
        "  else if (!isStatistics) refresh();\n")
    text = replace_once(
        'app.js route list', text,
        "  const page = route ? 'pack' : ['overview', 'packs', 'assets', 'statistics', 'configuration']\n",
        "  const page = route ? 'pack' : ['overview', 'packs', 'assets', 'statistics', 'extra-tools', 'configuration']\n")
    functions = r'''// Extra Tools: archive discovery and non-destructive extraction.
function updateArchiveSelectionControls() {
  const selectable = archiveItems.filter(item => item.supported && !item.destination_exists);
  const selectedCount = selectedArchiveIds.size;
  $('archive-selection-count').textContent = `${prettyNum(selectedCount)} selected`;
  $('extract-archives').disabled = archiveExtractionBusy || archiveListBusy || selectedCount === 0;
  $('extract-archives').textContent = archiveExtractionBusy ? 'Extracting archives…' : 'Extract archives';
  $('archives-refresh').disabled = archiveExtractionBusy || archiveListBusy;
  const selectAll = $('archives-select-all');
  selectAll.disabled = archiveExtractionBusy || archiveListBusy || selectable.length === 0;
  selectAll.checked = selectable.length > 0 && selectable.every(item => selectedArchiveIds.has(item.id));
  selectAll.indeterminate = !selectAll.checked && selectable.some(item => selectedArchiveIds.has(item.id));
}
function renderArchiveList() {
  $('archive-count').textContent = `${prettyNum(archiveItems.length)} archive${archiveItems.length === 1 ? '' : 's'} found`;
  const host = $('archive-list');
  if (!archiveItems.length) {
    host.innerHTML = '<div class="empty"><div class="empty-symbol">▤</div><strong>No archives found</strong><p>Download packages first, then refresh this list.</p></div>';
    updateArchiveSelectionControls();
    return;
  }
  const rows = archiveItems.map(item => {
    const disabled = !item.supported || item.destination_exists || archiveExtractionBusy;
    const status = !item.supported
      ? `<span class="archive-state unsupported">Unsupported (${escapeHtml(item.extension)})</span>`
      : item.destination_exists ? '<span class="archive-state exists">Destination exists · skipped</span>'
      : '<span class="archive-state ready">Ready to extract</span>';
    const rowClass = !item.supported ? ' unsupported' : item.destination_exists ? ' already-extracted' : '';
    return `<label class="archive-row${rowClass}">
      <input class="archive-select" type="checkbox" data-archive-id="${escapeHtml(item.id)}" ${selectedArchiveIds.has(item.id) ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
      <span class="archive-file"><strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong><small title="${escapeHtml(item.relative_path)}">${escapeHtml(item.relative_path)}</small></span>
      <span class="archive-package" title="${escapeHtml(item.package)}">${escapeHtml(item.package)}</span>
      <span class="archive-format">${escapeHtml(item.extension)}</span>
      <span class="archive-size">${prettySize(item.size)}</span>
      ${status}
    </label>`;
  }).join('');
  host.innerHTML = `<div class="archive-list-header"><span></span><span>Archive / source path</span><span>Package</span><span>Format</span><span>Size</span><span>Status</span></div>${rows}`;
  updateArchiveSelectionControls();
}
async function refreshArchiveList() {
  if (archiveListBusy || archiveExtractionBusy) return;
  archiveListBusy = true;
  $('archive-list').innerHTML = '<div class="loading">Scanning downloaded archives…</div>';
  updateArchiveSelectionControls();
  try {
    const data = await api('/api/archives');
    archiveItems = Array.isArray(data.archives) ? data.archives : [];
    const present = new Set(archiveItems.map(item => item.id));
    for (const id of selectedArchiveIds) if (!present.has(id)) selectedArchiveIds.delete(id);
    renderArchiveList();
  } catch (err) {
    $('archive-list').innerHTML = `<div class="empty"><strong>Could not load archives</strong><p>${escapeHtml(err.message)}</p></div>`;
  } finally {
    archiveListBusy = false;
    updateArchiveSelectionControls();
  }
}
function renderArchiveResults(results) {
  const details = $('archive-operation-details');
  if (!results.length) { details.hidden = true; details.innerHTML = ''; return; }
  details.hidden = false;
  details.innerHTML = results.map(item => {
    const cls = item.status === 'extracted' ? 'ready' : item.status === 'skipped' ? 'exists' : 'unsupported';
    return `<div class="archive-result-row"><span class="archive-state ${cls}">${escapeHtml(item.status)}</span><span><strong>${escapeHtml(item.name || 'Archive')}</strong><small>${escapeHtml(item.message || '')}</small></span></div>`;
  }).join('');
}
async function extractSelectedArchives() {
  const ids = archiveItems.filter(item => selectedArchiveIds.has(item.id) && item.supported && !item.destination_exists)
    .map(item => item.id);
  if (!ids.length || archiveExtractionBusy) return;
  if (!window.confirm(`Extract ${ids.length} selected archive(s)? Original archives will be preserved. Existing destination folders will be skipped.`)) return;
  archiveExtractionBusy = true;
  $('archive-operation-details').hidden = true;
  $('archive-operation-status').textContent = `Extracting ${ids.length} archive(s). This may take a while; keep Local Dex running.`;
  renderArchiveList();
  try {
    const data = await post('/api/extract-archives', { ids });
    const counts = data.counts || {};
    const summary = `Extraction finished: ${prettyNum(counts.extracted || 0)} extracted, ${prettyNum(counts.skipped || 0)} skipped, ${prettyNum(counts.failed || 0)} failed.`;
    $('archive-operation-status').textContent = summary;
    renderArchiveResults(Array.isArray(data.results) ? data.results : []);
    selectedArchiveIds.clear();
    toast(summary);
    archiveExtractionBusy = false;
    await refreshArchiveList();
  } catch (err) {
    $('archive-operation-status').textContent = `Extraction failed: ${err.message}`;
    toast('Archive extraction failed: ' + err.message);
  } finally {
    archiveExtractionBusy = false;
    updateArchiveSelectionControls();
  }
}

'''
    text = replace_once(
        'app.js Extra Tools functions', text,
        '// Configuration operations always run locally via the Dex server, not in the browser.\n',
        functions + '// Configuration operations always run locally via the Dex server, not in the browser.\n')
    text = replace_once(
        'app.js Extra Tools bindings', text,
        "  $('config-recheck').addEventListener('click', () => refreshConfiguration(true));\n",
        "  $('config-recheck').addEventListener('click', () => refreshConfiguration(true));\n"
        "  $('archives-refresh').addEventListener('click', refreshArchiveList);\n"
        "  $('archives-select-all').addEventListener('change', ev => {\n"
        "    if (ev.target.checked) archiveItems.filter(item => item.supported && !item.destination_exists)\n"
        "      .forEach(item => selectedArchiveIds.add(item.id));\n"
        "    else selectedArchiveIds.clear();\n"
        "    renderArchiveList();\n"
        "  });\n"
        "  $('archive-list').addEventListener('change', ev => {\n"
        "    const checkbox = ev.target.closest('.archive-select');\n"
        "    if (!checkbox) return;\n"
        "    if (checkbox.checked) selectedArchiveIds.add(checkbox.dataset.archiveId);\n"
        "    else selectedArchiveIds.delete(checkbox.dataset.archiveId);\n"
        "    updateArchiveSelectionControls();\n"
        "  });\n"
        "  $('extract-archives').addEventListener('click', extractSelectedArchives);\n")
    return text


def patch_css(text: str) -> str:
    if '/* Extra Tools: archive extraction */' in text:
        raise PatchError('styles.css already contains the Extra Tools styles; refusing to duplicate them.')
    return text + r'''

/* Extra Tools: archive extraction */
.extra-tools-view { width: 100%; }
.extra-tools-heading { align-items: center; padding-bottom: 16px; border-bottom: 1px solid var(--stroke); }
.extra-tools-heading .btn { flex: 0 0 auto; }
.archive-selection-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; margin: 20px 0 12px; padding: 14px 15px; border: 1px solid var(--stroke); border-radius: 10px; background: var(--panel); }
.archive-select-all { display: inline-flex; align-items: center; gap: 9px; font-weight: 750; color: var(--txt); }
.archive-select-all input, .archive-select { accent-color: var(--pink); width: 16px; height: 16px; }
.archive-summary-count { color: var(--sub); font-size: 12px; }
.archive-selection-count { margin-left: auto; color: var(--sub); font-size: 12px; }
.archive-operation-status { margin: 10px 0 14px; padding: 11px 13px; border-left: 3px solid var(--purple); border-radius: 5px; background: var(--panel2); color: var(--sub); font-size: 12px; line-height: 1.6; }
.archive-operation-details { display: grid; gap: 7px; margin: 0 0 18px; }
.archive-result-row { display: grid; grid-template-columns: 90px minmax(0,1fr); align-items: start; gap: 12px; padding: 10px 12px; border: 1px solid var(--stroke); border-radius: 7px; background: var(--panel); }
.archive-result-row strong, .archive-result-row small { display: block; overflow-wrap: anywhere; }
.archive-result-row strong { font-size: 11px; }
.archive-result-row small { margin-top: 4px; color: var(--sub); font-size: 11px; line-height: 1.45; }
.archive-list { width: 100%; border: 1px solid var(--stroke); border-radius: 10px; overflow: hidden; background: var(--panel); }
.archive-list-header, .archive-row { display: grid; grid-template-columns: 22px minmax(180px,2.5fr) minmax(90px,1.2fr) 72px 78px minmax(130px,1.2fr); align-items: center; gap: 12px; padding: 11px 13px; }
.archive-list-header { background: var(--panel2); border-bottom: 1px solid var(--stroke); color: var(--muted); font-size: 9px; font-weight: 850; letter-spacing: .8px; text-transform: uppercase; }
.archive-row { border-bottom: 1px solid var(--stroke); color: var(--txt); cursor: pointer; min-width: 0; }
.archive-row:last-child { border-bottom: 0; }
.archive-row:hover { background: color-mix(in srgb, var(--pink) 5%, var(--panel)); }
.archive-row.already-extracted, .archive-row.unsupported { color: var(--sub); cursor: default; }
.archive-file { display: block; min-width: 0; }
.archive-file strong, .archive-file small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.archive-file strong { font-size: 11px; font-weight: 750; }
.archive-file small { margin-top: 5px; color: var(--muted); font-family: Consolas, monospace; font-size: 10px; }
.archive-package, .archive-format, .archive-size { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--sub); font-size: 11px; }
.archive-state { font-size: 10px; font-weight: 750; line-height: 1.4; }
.archive-state.ready { color: var(--green); }
.archive-state.exists { color: var(--sub); }
.archive-state.unsupported { color: #d58a70; }
@media (max-width: 1050px) {
  .archive-list-header { display: none; }
  .archive-row { grid-template-columns: 20px minmax(0,1fr) auto; gap: 9px; }
  .archive-file { grid-column: 2; }
  .archive-package { grid-column: 2; }
  .archive-format, .archive-size, .archive-state { grid-column: 3; text-align: right; }
  .archive-package { display: none; }
}
@media (max-width: 600px) {
  .extra-tools-heading { align-items: flex-start; flex-direction: column; }
  .archive-selection-count { margin-left: 0; }
  .archive-selection-bar .btn { flex: 1 1 100%; }
  .archive-row { grid-template-columns: 18px minmax(0,1fr); }
  .archive-format, .archive-size, .archive-state { grid-column: 2; text-align: left; }
}
'''


def patch_readme(text: str) -> str:
    if 'Extra tools | Select downloaded archives' in text:
        raise PatchError('README.md already documents Extra tools; refusing to duplicate the entry.')
    target = '| Configuration  | Check setup readiness, install/repair dependencies, edit root `config.yaml`, synchronize downloads, rebuild the index, view execution timestamps, status and logs. |'
    replacement = '| Extra tools | Select downloaded archives and extract supported ZIP, TAR, TGZ, GZ and Unity package archives into sibling folders. Originals are preserved; existing extraction folders are skipped. |\n' + target
    if target not in text:
        # The table may have slightly different spacing; match the exact configuration row by content.
        lines = text.splitlines(keepends=True)
        matches = [i for i, line in enumerate(lines)
                   if 'Configuration' in line and 'Check setup readiness' in line and 'config.yaml' in line]
        if len(matches) != 1:
            raise PatchError(f'README.md: expected one Configuration feature row, found {len(matches)}. No project files were changed.')
        line = lines[matches[0]]
        newline = '\n' if line.endswith('\n') else ''
        lines.insert(matches[0], '| Extra tools | Select downloaded archives and extract supported ZIP, TAR, TGZ, GZ and Unity package archives into sibling folders. Originals are preserved; existing extraction folders are skipped. |\n')
        return ''.join(lines)
    return text.replace(target, replacement, 1)


def main() -> int:
    files = {
        ROOT / 'SyntyLocalDex' / 'local_dex_server.py': patch_server,
        ROOT / 'SyntyLocalDex' / 'local_dex_web' / 'index.html': patch_html,
        ROOT / 'SyntyLocalDex' / 'local_dex_web' / 'app.js': patch_js,
        ROOT / 'SyntyLocalDex' / 'local_dex_web' / 'styles.css': patch_css,
        ROOT / 'README.md': patch_readme,
    }
    if not (ROOT / 'SyntyLocalDex' / 'archive_extractor.py').is_file():
        print('ERROR: SyntyLocalDex/archive_extractor.py is missing. Extract the complete update ZIP first.', file=sys.stderr)
        return 2
    all_targets = list(files)
    for path in all_targets:
        if not path.is_file():
            print(f'ERROR: required project file not found: {path.relative_to(ROOT)}', file=sys.stderr)
            return 2

    # Idempotence: if every integration marker is already present, do nothing.
    markers = [
        (ROOT / 'SyntyLocalDex' / 'local_dex_server.py', "/api/extract-archives"),
        (ROOT / 'SyntyLocalDex' / 'local_dex_web' / 'index.html', 'id="extra-tools-view"'),
        (ROOT / 'SyntyLocalDex' / 'local_dex_web' / 'app.js', 'async function extractSelectedArchives()'),
        (ROOT / 'SyntyLocalDex' / 'local_dex_web' / 'styles.css', '/* Extra Tools: archive extraction */'),
        (ROOT / 'README.md', 'Extra tools | Select downloaded archives'),
    ]
    if all(marker in path.read_text(encoding='utf-8') for path, marker in markers):
        print('Extra Tools archive extraction is already installed; no changes made.')
        return 0

    updated: dict[Path, str] = {}
    try:
        for path, transform in files.items():
            updated[path] = transform(path.read_text(encoding='utf-8'))
    except PatchError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2

    backup_root = Path(tempfile.mkdtemp(prefix='localdex-extra-tools-backup-'))
    try:
        for path in files:
            backup = backup_root / path.relative_to(ROOT)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        for path, content in updated.items():
            path.write_text(content, encoding='utf-8', newline='\n')
    except OSError as exc:
        print(f'ERROR: failed to write patch files: {exc}', file=sys.stderr)
        print(f'Original file backups are in: {backup_root}', file=sys.stderr)
        return 3

    print('Extra Tools archive extraction patch applied successfully.')
    print('Updated:')
    for path in files:
        print(f'  - {path.relative_to(ROOT)}')
    print(f'Backups of original files: {backup_root}')
    print('Next: run the LocalDex Python tests, then restart launch_localdex.cmd and open Extra tools.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
