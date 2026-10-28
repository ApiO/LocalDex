// SPDX-License-Identifier: GPL-3.0-only
'use strict';

const state = {
  catalog: null, token: '', page: 'overview', search: '', collection: '', kind: '',
  category: '', engine: '', pack: '', packTab: 'assets', currentPage: 1,
  perPage: 48, total: 0, items: [], selected: null
};
const $ = id => document.getElementById(id);
const escapeHtml = (value = '') => String(value).replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const prettyNum = n => Number(n || 0).toLocaleString('en-US');
const prettySize = n => {
  let v = Number(n) || 0, k = 0;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  while (v >= 1024 && k < units.length - 1) { v /= 1024; k++; }
  return (k === 0 ? v.toFixed(0) : v.toFixed(1)) + ' ' + units[k];
};
const initials = n => (String(n).replace(/^(POLYGON|ANIMATION|INTERFACE|SIMPLE|SIDEKICK)\s*[-–]?\s*/i, '')
  .trim().split(/[\s_-]+/).slice(0, 2).map(x => x.slice(0, 1)).join('').toUpperCase() || 'S');
const icons = {
  Model: '⬡', Prefab: '◈', Character: '♟', Animation: '◷', Texture: '▨',
  Image: '▧', 'UI / sprite': '◫', Archive: '▤', 'Unity package': '⬢',
  'Material / shader': '✧', Audio: '♫', 'Unreal asset': '⬡', Code: '⌘',
  Document: '≡', Scene: '▧', Video: '▶', Other: '◇'
};
const collectionColor = {
  Polygon: '#b967da', Animation: '#e88b57', Interface: '#5fbdde',
  Sidekick: '#f36da2', Simple: '#51caac', Other: '#8b90a0'
};
const imageExt = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif']);
const videoExt = new Set(['.mp4', '.webm']);
const audioExt = new Set(['.mp3', '.wav', '.ogg']);
let searchTimer, toastTimer, requestId = 0, viewerToken = 0, closeFbxViewer = null;
const THEME_KEY = 'synty-local-dex-theme-v1';
const SIDEBAR_COLLAPSED_KEY = 'synty-local-dex-sidebar-collapsed-v1';
const ASSET_VIEW_KEY = 'synty-local-dex-assets-view-v1';
const PACK_VIEW_KEY = 'synty-local-dex-pack-view-v1';
let assetViewMode = 'grid';
let packViewMode = 'grid';
let archiveItems = [];
let availableArchiveFormats = [];
let allArchiveFormatsSelected = true;
const selectedArchiveFormats = new Set();
const selectedArchiveIds = new Set();
const collapsedArchivePackages = new Set();
function setSidebarCollapsed(collapsed, persist = false) {
  const root = document.documentElement;
  if (collapsed) root.dataset.sidebarCollapsed = 'true';
  else delete root.dataset.sidebarCollapsed;
  const toggle = $('sidebar-toggle');
  if (toggle) {
    const label = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
    toggle.setAttribute('aria-label', label);
    toggle.setAttribute('title', label);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.innerHTML = `<span aria-hidden="true">${collapsed ? '›' : '‹'}</span>`;
  }
  if (persist) {
    try { localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? '1' : '0'); }
    catch (_) { /* Keep the current session's preference if storage is unavailable. */ }
  }
}
let archiveListBusy = false;
let archiveExtractionBusy = false;
let archiveExtractionJobId = null;
let archiveProgressLogSignature = '';
let archiveProgressEntries = [];
let archiveLogFailuresOnly = false;
const AUTO_LOAD_MARGIN = 400;
let listingBusy = false;
let autoMoreBlocked = false;

// Window scrolling drives pagination; the button remains a manual fallback.
// Only asset lists (including the Assets / Downloaded files tabs inside a pack)
// are paginated. Packs, Statistics, Configuration and Overview are not.
function canLoadMore(auto = false) {
  return state.catalog && (state.page === 'assets' || state.page === 'pack')
    && !$('browse-view').hidden && !$('load-more').hidden
    && !listingBusy && (!auto || !autoMoreBlocked)
    && state.items.length < state.total;
}
function requestMore(auto = false) {
  if (!canLoadMore(auto)) return;
  if (!auto) autoMoreBlocked = false; // Manual retry after an error/empty page.
  state.currentPage += 1;
  refresh(true);
}
function checkAutoLoadMore() {
  if (!canLoadMore(true)) return;
  const rect = $('load-more').parentElement.getBoundingClientRect();
  if (rect.top <= window.innerHeight + AUTO_LOAD_MARGIN && rect.bottom >= 0) requestMore(true);
}
function initAutoLoadMore() {
  const marker = $('load-more').parentElement;
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) requestMore(true);
    }, { root: null, rootMargin: `0px 0px ${AUTO_LOAD_MARGIN}px 0px`, threshold: 0 })
      .observe(marker);
  } else {
    window.addEventListener('scroll', checkAutoLoadMore, { passive: true });
  }
  window.addEventListener('resize', checkAutoLoadMore, { passive: true });
}

// Drag the left edge of the right-hand inspector. The CSS grid takes the
// panel width from --details-width, so the active asset listing contracts naturally.
let detailsWidth = null;
let detailsResizePointer = null;
function detailsWidthLimits() {
  if (window.innerWidth <= 1160) {
    return { min: Math.min(340, window.innerWidth), max: Math.min(680, window.innerWidth) };
  }
  const base = window.innerWidth <= 1430 ? 285 : 320;
  return { min: base, max: base * 2 };
}
function updateDetailsResizeAria() {
  const { min, max } = detailsWidthLimits();
  const handle = $('details-resize-handle');
  const current = detailsWidth === null ? min : Math.min(max, Math.max(min, detailsWidth));
  handle.setAttribute('aria-valuemin', String(min));
  handle.setAttribute('aria-valuemax', String(max));
  handle.setAttribute('aria-valuenow', String(Math.round(current)));
  handle.setAttribute('aria-valuetext', `${Math.round(current)} pixels wide`);
}
function setDetailsWidth(px) {
  const { min, max } = detailsWidthLimits();
  detailsWidth = Math.max(min, Math.min(max, Math.round(px)));
  document.querySelector('.app-shell').style.setProperty('--details-width', `${detailsWidth}px`);
  updateDetailsResizeAria();
}
function resetDetailsWidth() {
  detailsWidth = null;
  document.querySelector('.app-shell').style.removeProperty('--details-width');
  updateDetailsResizeAria();
}
function initDetailsResize() {
  const handle = $('details-resize-handle');
  handle.addEventListener('pointerdown', ev => {
    if (ev.button !== 0 || $('details-panel').hidden) return;
    ev.preventDefault();
    const currentWidth = $('details-panel').getBoundingClientRect().width;
    detailsResizePointer = { id: ev.pointerId, x: ev.clientX, width: currentWidth };
    handle.setPointerCapture(ev.pointerId);
    document.body.classList.add('details-resizing');
  });
  handle.addEventListener('pointermove', ev => {
    if (!detailsResizePointer || detailsResizePointer.id !== ev.pointerId) return;
    setDetailsWidth(detailsResizePointer.width + detailsResizePointer.x - ev.clientX);
  });
  function finishResize(ev) {
    if (!detailsResizePointer || detailsResizePointer.id !== ev.pointerId) return;
    detailsResizePointer = null;
    document.body.classList.remove('details-resizing');
    if (handle.hasPointerCapture(ev.pointerId)) handle.releasePointerCapture(ev.pointerId);
  }
  handle.addEventListener('pointerup', finishResize);
  handle.addEventListener('pointercancel', finishResize);
  handle.addEventListener('lostpointercapture', ev => {
    if (detailsResizePointer?.id === ev.pointerId) {
      detailsResizePointer = null;
      document.body.classList.remove('details-resizing');
    }
  });
  handle.addEventListener('dblclick', resetDetailsWidth);
  handle.addEventListener('keydown', ev => {
    const { min, max } = detailsWidthLimits();
    let next;
    if (ev.key === 'ArrowLeft') next = (detailsWidth ?? min) + 16;
    else if (ev.key === 'ArrowRight') next = (detailsWidth ?? min) - 16;
    else if (ev.key === 'Home') next = min;
    else if (ev.key === 'End') next = max;
    else return;
    ev.preventDefault();
    setDetailsWidth(next);
  });
  window.addEventListener('resize', () => {
    if (detailsWidth !== null) setDetailsWidth(detailsWidth);
    else updateDetailsResizeAria();
  }, { passive: true });
  updateDetailsResizeAria();
}

function applyTheme(theme, persist = false) {
  const next = theme === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  $('theme-icon').textContent = next === 'light' ? '☾' : '☀';
  $('theme-label').textContent = next === 'light' ? 'Dark theme' : 'Light theme';
  $('theme-toggle').setAttribute('aria-label', `Switch to ${next === 'light' ? 'dark' : 'light'} theme`);
  $('theme-toggle').setAttribute('aria-pressed', String(next === 'light'));
  if (persist) {
    try { localStorage.setItem(THEME_KEY, next); }
    catch (_) { toast('Browser storage unavailable: theme will not persist.'); }
  }
}
function toggleTheme() { applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light', true); }


function toast(message) {
  const node = $('toast'); node.textContent = message; node.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => node.classList.remove('show'), 3500);
}
async function api(path, opts = {}) {
  const response = await fetch(path, { cache: 'no-store', ...opts });
  let value;
  try { value = await response.json(); } catch { throw Error('Could not read server response'); }
  if (!response.ok) throw Error(value.error || `HTTP ${response.status}`);
  return value;
}
async function post(path, data) {
  return api(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Localdex-Token': state.token },
    body: JSON.stringify(data)
  });
}
const previewUrl = a => `/api/preview/${encodeURIComponent(a.id)}`;
const cover = p => p.cover
  ? `<img loading="lazy" src="/api/cover/${encodeURIComponent(p.cover.split('/').pop())}" alt="">`
  : `<span class="cover-graphic">${escapeHtml(initials(p.name))}</span><span class="cover-geos"></span>`;
const pill = (label, klass = '') => `<span class="pill ${klass}">${escapeHtml(label)}</span>`;

function packCard(p) {
  return `<button type="button" class="pack-card" data-action="select-pack" data-id="${escapeHtml(p.id)}"
    aria-label="Browse contents of ${escapeHtml(p.name)}">
    <div class="pack-cover ${escapeHtml((p.collection || 'Other').toLowerCase())}">${cover(p)}
      <span class="pack-flag">${escapeHtml(p.collection.toUpperCase())}</span></div>
    <div class="pack-info"><div class="pack-name">${escapeHtml(p.name)}</div>
    <div class="pack-secondary">${escapeHtml(p.theme === 'Other' ? 'Asset collection' : p.theme + ' collection')}</div>
    <div class="pack-bottom"><span>${prettyNum(p.assets)} assets · ${prettyNum(p.files)} files</span><span class="arrow">→</span></div></div>
  </button>`;
}
function assetCard(a) {
  const ext = (a.ext || '').toLowerCase();
  const thumb = imageExt.has(ext);
  const fbx = ext === '.fbx';
  const filename = escapeHtml(a.name); // Preserve full filename AND extension.
  return `<button type="button" class="asset-card ${state.selected?.id === a.id ? 'selected' : ''}"
    data-action="select-asset" data-id="${escapeHtml(a.id)}" aria-label="Inspect ${filename}">
    <div class="asset-thumb">${thumb
      ? `<img loading="lazy" src="${previewUrl(a)}" alt="" class="asset-thumb-image">`
      : fbx ? `<img loading="lazy" src="/api/fbx-thumb/${encodeURIComponent(a.id)}" alt="" class="asset-thumb-image">`
      : `<span class="asset-kind-icon">${icons[a.kind] || '◇'}</span>`}</div>
    <div class="asset-card-meta"><div class="asset-tags">${pill(a.kind, 'pink')}${a.engine !== 'Any' ? pill(a.engine) : ''}</div>
      <span class="asset-info" title="${filename}" aria-label="File: ${filename}">
        <span class="asset-info-icon" aria-hidden="true">i</span>
        <span class="asset-info-tooltip" role="tooltip">${filename}</span>
      </span>
    </div>
  </button>`;
}

// A compact row view works in Assets and Pack Explorer (both pack tabs).
// Both formats reuse the same select-asset action as the grid cards.
function assetListRow(a) {
  const ext = (a.ext || '').toLowerCase();
  const filename = escapeHtml(a.name);
  const path = escapeHtml(a.inner_path || a.source_rel || '');
  const thumbnail = imageExt.has(ext)
    ? `<img loading="lazy" src="${previewUrl(a)}" alt="" class="asset-thumb-image">`
    : ext === '.fbx'
      ? `<img loading="lazy" src="/api/fbx-thumb/${encodeURIComponent(a.id)}" alt="" class="asset-thumb-image">`
      : `<span class="asset-kind-icon">${icons[a.kind] || '◇'}</span>`;
  return `<button type="button" class="asset-list-row ${state.selected?.id === a.id ? 'selected' : ''}"
    data-action="select-asset" data-id="${escapeHtml(a.id)}" aria-label="Inspect ${filename}">
    <span class="asset-list-thumb">${thumbnail}</span>
    <span class="asset-list-description"><strong title="${filename}">${filename}</strong>
      <small title="${path}">${path}</small></span>
    <span class="asset-list-pack" title="${escapeHtml(a.pack_name || '')}">${escapeHtml(a.pack_name || '')}</span>
    <span class="asset-list-type">${pill(a.kind, 'pink')}</span>
    <span class="asset-list-engine">${a.engine && a.engine !== 'Any' ? pill(a.engine) : '<span class="list-muted">—</span>'}</span>
  </button>`;
}
function listingIsList() {
  return (state.page === 'assets' && assetViewMode === 'list')
    || (state.page === 'pack' && packViewMode === 'list');
}
function listColumnHeaders() {
  return `<div class="asset-list-columns" aria-hidden="true"><span>Preview</span><span>Filename / source path</span><span>Package</span><span>Type</span><span>Engine</span></div>`;
}
function listingMarkup(items) {
  return items.map(listingIsList() ? assetListRow : assetCard).join('');
}
function renderListingFromState() {
  if (state.page !== 'assets' && state.page !== 'pack') return;
  const node = $('results');
  node.className = listingIsList() ? 'asset-list' : 'pack-grid';
  if (!state.items.length) return; // Preserve loading or error placeholders.
  node.innerHTML = (listingIsList() ? listColumnHeaders() : '') + listingMarkup(state.items);
  requestAnimationFrame(checkAutoLoadMore);
}
function updateListingViewButtons() {
  const current = state.page === 'pack' ? packViewMode : assetViewMode;
  for (const option of ['grid', 'list']) {
    const btn = $(`asset-view-${option}`);
    const selected = current === option;
    btn.classList.toggle('active', selected);
    btn.setAttribute('aria-pressed', String(selected));
  }
}
function applyAssetView(mode, persist = true) {
  const next = mode === 'list' ? 'list' : 'grid';
  const inPack = state.page === 'pack';
  if (inPack) packViewMode = next;
  else assetViewMode = next;
  updateListingViewButtons();
  if (persist) {
    try { localStorage.setItem(inPack ? PACK_VIEW_KEY : ASSET_VIEW_KEY, next); }
    catch (_) { /* Fall back to the in-memory preference. */ }
  }
  renderListingFromState();
}

function renderSidebar() {
  $('side-pack-count').textContent = prettyNum(state.catalog.stats.packs);
  $('side-asset-count').textContent = prettyNum(state.catalog.stats.assets);
  const collections = state.catalog.stats.collections;
  $('sidebar-collections').innerHTML = Object.keys(collections).sort().map(name =>
    `<button class="nav-link ${state.page === 'packs' && state.collection === name ? 'active' : ''}"
      data-action="collection" data-name="${escapeHtml(name)}" aria-label="Collection: ${escapeHtml(name)}" title="${escapeHtml(name)}">
      <span class="side-collection-dot" aria-hidden="true" style="background:${collectionColor[name] || '#8b90a0'}"></span>
      ${escapeHtml(name)}<span class="nav-count">${prettyNum(collections[name])}</span></button>`).join('');
  $('collection-filter').innerHTML = '<option value="">All collections</option>' + Object.keys(collections).sort()
    .map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
  $('kind-filter').innerHTML = '<option value="">All asset types</option>' + state.catalog.stats.kinds
    .map(e => `<option value="${escapeHtml(e.name)}">${escapeHtml(e.name)}</option>`).join('');
  $('category-filter').innerHTML = '<option value="">All categories</option>' + (state.catalog.stats.categories || [])
    .map(e => `<option value="${escapeHtml(e.name)}">${escapeHtml(e.name)}</option>`).join('');
  for (const key of ['collection', 'kind', 'category']) $(`${key}-filter`).value = state[key];
}
// Simple rows (rather than asset cards) make statistics readable even for large libraries.
function renderStatsRows(targetId, values, formatValue = prettyNum) {
  const host = $(targetId);
  const entries = (values || []).filter(x => Number(x.count) > 0);
  if (!entries.length) {
    host.innerHTML = '<p class="stats-empty">No data indexed yet.</p>';
    return;
  }
  const largest = Math.max(...entries.map(x => Number(x.count) || 0), 1);
  host.innerHTML = entries.map(entry => {
    const count = Number(entry.count) || 0;
    const width = Math.max(0, Math.min(100, count / largest * 100));
    return `<div class="stats-row"><div class="stats-row-line">
      <span class="stats-row-name" title="${escapeHtml(entry.name)}">${escapeHtml(entry.name)}</span>
      <span class="stats-row-value">${escapeHtml(formatValue(count))}</span>
      </div><div class="stats-row-bar"><span data-progress="${width.toFixed(2)}"></span></div></div>`;
  }).join('');
  host.querySelectorAll('[data-progress]').forEach(bar => {
    bar.style.width = `${Number(bar.dataset.progress)}%`;
  });
}

function renderStats() {
  const s = state.catalog.stats;
  $('stat-packs').textContent = prettyNum(s.packs);
  $('stat-assets').textContent = prettyNum(s.assets);
  $('stat-files').textContent = prettyNum(s.download_files);
  $('stat-bytes').textContent = prettySize(s.total_bytes);
  renderStatsRows('stats-collections', Object.entries(s.collections || {})
    .map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)));
  renderStatsRows('stats-types', s.kinds);
  renderStatsRows('stats-categories', s.categories);
  renderStatsRows('stats-largest', [...state.catalog.packs]
    .sort((a, b) => b.bytes - a.bytes).slice(0, 10)
    .map(p => ({ name: p.name, count: p.bytes })), prettySize);
  const date = new Date(state.catalog.generated_at);
  $('index-date').textContent = isNaN(date.valueOf()) ? 'Catalog loaded' : `Indexed ${date.toLocaleDateString()}`;
}
function archiveScanVisualMarkup() {
  return `<span class="archive-scan-visual" aria-hidden="true">
    <span class="archive-scan-file">
      <span class="archive-scan-fold"></span>
      <span class="archive-scan-line line-a"></span>
      <span class="archive-scan-line line-b"></span>
      <span class="archive-scan-line line-c"></span>
      <span class="archive-scan-line line-d"></span>
    </span>
    <span class="archive-scan-beam"></span>
  </span>`;
}
function archiveScanningLoadingMarkup(message, className = '') {
  return `<div class="loading archive-scanning-loading ${className}" role="status" aria-live="polite">
    ${archiveScanVisualMarkup()}<span class="archive-scan-message">${escapeHtml(message)}</span>
  </div>`;
}
function extractionHistoryLoadingMarkup() {
  return `<span class="stats-history-loading" role="status" aria-live="polite">
    <span class="stats-history-scan" aria-hidden="true"><span class="stats-history-scan-scale">${archiveScanVisualMarkup()}</span></span>
    <span>Loading extraction history…</span>
  </span>`;
}
let extractionStatsRequestId = 0;
let extractionStatsCache = null;
function renderExtractionStats(stats) {
  $('stat-extraction-archives').textContent = prettyNum(stats.supported_archives);
  $('stat-extraction-folders').textContent = prettyNum(stats.extraction_folders);
  $('stat-extraction-unextracted').textContent = prettyNum(stats.unextracted_archives);
  $('stat-extraction-recorded').textContent = prettyNum(stats.recorded_extractions);
  const latest = stats.latest_extraction_at ? new Date(stats.latest_extraction_at) : null;
  const latestLabel = latest && !Number.isNaN(latest.getTime()) ? latest.toLocaleString() : 'Never';
  $('stats-extraction-latest').textContent = `Latest successful extraction: ${latestLabel}`;
  $('stats-extraction-latest').title = stats.latest_extraction_at || '';
}
function showExtractionStatsLoading() {
  for (const id of ['stat-extraction-archives', 'stat-extraction-folders',
    'stat-extraction-unextracted', 'stat-extraction-recorded']) $(id).textContent = '…';
  $('stats-extraction-latest').innerHTML = extractionHistoryLoadingMarkup();
  $('stats-extraction-latest').title = 'Scanning the library for extraction history';
}
async function refreshExtractionStats() {
  const request = ++extractionStatsRequestId;
  if (extractionStatsCache) renderExtractionStats(extractionStatsCache);
  let loadingTimer = null;
  if (!extractionStatsCache) {
    loadingTimer = window.setTimeout(() => {
      if (request === extractionStatsRequestId && state.page === 'statistics' && !extractionStatsCache) showExtractionStatsLoading();
    }, 120);
  }
  try {
    let response = await api('/api/archive-statistics');
    if (loadingTimer !== null) window.clearTimeout(loadingTimer);
    while (request === extractionStatsRequestId && state.page === 'statistics') {
      const stats = response && response.stats ? response.stats
        : response && typeof response.supported_archives === 'number' ? response : null;
      if (stats) {
        extractionStatsCache = stats;
        renderExtractionStats(stats);
      } else if (response && response.loading && !extractionStatsCache) {
        if (!$('stats-extraction-latest').querySelector('.stats-history-loading')) showExtractionStatsLoading();
      }
      if (!response?.loading && !response?.refreshing) {
        if (!stats && !extractionStatsCache) {
          const message = response?.error || 'The extraction history could not be loaded.';
          for (const id of ['stat-extraction-archives', 'stat-extraction-folders',
            'stat-extraction-unextracted', 'stat-extraction-recorded']) $(id).textContent = '—';
          $('stats-extraction-latest').textContent = `Extraction statistics unavailable: ${message}`;
          $('stats-extraction-latest').title = message;
        }
        return;
      }
      // Cached stats are rendered immediately while a stale cache refreshes quietly.
      // Only a cold start (no cached stats at all) displays the animated loading state.
      await new Promise(resolve => window.setTimeout(resolve, response?.loading ? 350 : 1000));
      if (request !== extractionStatsRequestId || state.page !== 'statistics') return;
      response = await api('/api/archive-statistics');
    }
  } catch (err) {
    if (loadingTimer !== null) window.clearTimeout(loadingTimer);
    if (request !== extractionStatsRequestId) return;
    if (extractionStatsCache) {
      renderExtractionStats(extractionStatsCache);
      $('stats-extraction-latest').title = `Cached statistics; refresh failed: ${err.message}`;
    } else {
      for (const id of ['stat-extraction-archives', 'stat-extraction-folders',
        'stat-extraction-unextracted', 'stat-extraction-recorded']) $(id).textContent = '—';
      $('stats-extraction-latest').textContent = `Extraction statistics unavailable: ${err.message}`;
      $('stats-extraction-latest').title = err.message;
    }
  }
}
function packById() { return state.catalog.packs.find(p => p.id === state.pack); }
function showPackHeader() {
  const pack = packById();
  if (!pack) return;
  $('pack-detail-name').textContent = pack.name;
  $('pack-detail-cover').innerHTML = cover(pack);
  $('pack-detail-meta').innerHTML = `${pill(pack.collection, 'pink')} ${pill(pack.theme)}
    <span>${prettyNum(pack.assets)} assets</span><span>${prettyNum(pack.files)} downloaded files</span>
    <span>${prettySize(pack.bytes)}</span>`;
  document.querySelectorAll('[data-action="pack-tab"]').forEach(el => {
    const selected = el.dataset.tab === state.packTab;
    el.classList.toggle('active', selected);
    el.setAttribute('aria-pressed', String(selected));
  });
}
function applyPage(page, resetFilters = false) {
  viewerToken++; if (closeFbxViewer) { closeFbxViewer(); closeFbxViewer = null; }
  state.page = page; state.currentPage = 1; state.items = []; state.total = 0;
  if (resetFilters) clearFilters(false);
  const isPack = page === 'pack';
  const isStatistics = page === 'statistics';
  const isConfiguration = page === 'configuration';
  const isExtraTools = page === 'extra-tools';
  const showDetails = page === 'assets' || isPack;
  $('details-panel').hidden = !showDetails;
  document.querySelector('.app-shell').classList.toggle('has-details', showDetails);
  if (!showDetails) $('details-panel').classList.remove('open');
  // A pending asset search must never change a standalone page.
  if (isStatistics || isConfiguration || isExtraTools) ++requestId;
  $('statistics-view').hidden = !isStatistics;
  $('configuration-view').hidden = !isConfiguration;
  $('extra-tools-view').hidden = !isExtraTools;
  $('browse-view').hidden = isStatistics || isConfiguration || isExtraTools;
  $('pack-detail').hidden = !isPack;
  $('section-top').hidden = isPack;
  $('asset-view-toggle').hidden = !showDetails;
  updateListingViewButtons();
  if (isPack) {
    if (!packById()) return navigate('packs');
    showPackHeader();
  } else {
    const descriptions = {
      overview: ['Your asset packs', 'A home for everything you have downloaded.'],
      packs: ['Browse asset packs', 'Find a pack by collection, name or theme.'],
      assets: ['Asset explorer', 'Find individual models, prefabs, textures and files inside archives.'],
      statistics: ['Statistics', 'Packages, files, categories and disk usage.']
    };
    const [title, subtitle] = descriptions[page] || descriptions.overview;
    $('section-title').textContent = title; $('section-subtitle').textContent = subtitle;
    updatePackPageTitle();
  }
  document.querySelectorAll('[data-page]').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  const showAssetFilters = isPack ? state.packTab === 'assets' : page === 'assets';
  $('kind-filter').hidden = !showAssetFilters;
  $('category-filter').hidden = !showAssetFilters;
  $('engine-filter').hidden = !showAssetFilters;
  $('collection-filter').hidden = isPack;
  for (const key of ['collection', 'kind', 'category', 'engine']) $(`${key}-filter`).value = state[key];
  $('search-input').placeholder = isPack ? `Search within ${packById().name}...`
    : page === 'assets' ? 'Search models, names, file paths...' : 'Search pack name, collection, theme...';
  renderSidebar();
  if (isConfiguration) refreshConfiguration();
  else if (isExtraTools) refreshArchiveList();
  else if (isStatistics) refreshExtractionStats();
  else refresh();
}
function clearFilters(refreshNow = true) {
  for (const key of ['search', 'collection', 'kind', 'category', 'engine']) state[key] = '';
  $('search-input').value = '';
  for (const key of ['collection', 'kind', 'category', 'engine']) $(`${key}-filter`).value = '';
  if (refreshNow) refresh();
}
function navigate(page, id = '') {
  const hash = page === 'pack' ? `#/pack/${encodeURIComponent(id)}` : `#/${page}`;
  if (location.hash === hash) routeFromHash(); else location.hash = hash;
}
function routeFromHash() {
  if (!state.catalog) return;
  const route = location.hash.match(/^#\/pack\/([0-9a-f]{24})$/i);
  const page = route ? 'pack' : ['overview', 'packs', 'assets', 'statistics', 'extra-tools', 'configuration']
    .includes(location.hash.slice(2)) ? location.hash.slice(2) : 'overview';
  const newPack = route ? route[1] : '';
  if (page !== state.page || newPack !== state.pack) {
    clearFilters(false); state.packTab = 'assets';
    resetAssetDetails();
    $('details-panel').classList.remove('open');
  }
  state.pack = newPack;
  applyPage(page);
}
function filtersChanged() {
  for (const key of ['collection', 'kind', 'category', 'engine']) state[key] = $(`${key}-filter`).value;
  refresh();
}
// Show the selected collection name on the pack listing, regardless of whether
// it was selected from the left sidebar or the collection filter dropdown.
function updatePackPageTitle() {
  if (state.page !== 'packs') return;
  $('section-title').textContent = state.collection
    ? `COLLECTION: ${state.collection}` : 'Browse asset packs';
}
function renderPacks() {
  updatePackPageTitle();
  ++requestId;
  listingBusy = false;
  autoMoreBlocked = false;
  const words = state.search.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const packs = state.catalog.packs.filter(p => (!state.collection || p.collection === state.collection)
    && words.every(w => [p.name, p.collection, p.theme].join(' ').toLowerCase().includes(w)));
  state.total = packs.length;
  $('result-count').textContent = prettyNum(packs.length); $('result-label').textContent = 'packs found';
  $('filter-note').textContent = '';
  $('results').className = 'pack-grid';
  $('results').innerHTML = packs.length ? packs.map(packCard).join('')
    : '<div class="empty"><div class="empty-symbol">⌕</div><strong>No matching packs</strong><p>Try a broader search or another collection.</p></div>';
  $('load-more').hidden = true;
}
async function refresh(more = false) {
  if (state.page === 'overview' || state.page === 'packs') return renderPacks();
  const id = ++requestId;
  listingBusy = true;
  const view = state.page === 'pack' ? state.packTab : state.page;
  $('filter-note').textContent = state.page === 'pack' ? '· This pack only' : '';
  if (!more) {
    state.currentPage = 1; state.items = [];
    autoMoreBlocked = false;
    $('load-more').hidden = true;
    $('results').innerHTML = archiveScanningLoadingMarkup('Searching the local index…', 'index-scanning-loading');
  }
  const params = new URLSearchParams({ view, q: state.search, collection: state.collection,
    kind: state.kind, category: state.category, engine: state.engine,
    pack: state.page === 'pack' ? state.pack : '', page: state.currentPage, limit: state.perPage });
  try {
    const result = await api('/api/search?' + params);
    if (id !== requestId) return;
    const nextItems = Array.isArray(result.items) ? result.items : [];
    state.total = result.total;
    if (more) {
      if (nextItems.length) {
        state.items.push(...nextItems);
        // Append rather than re-render all cards: preserves existing thumbnails,
        // scroll position and any previews already loaded in the grid.
        $('results').insertAdjacentHTML('beforeend', listingMarkup(nextItems));
      } else {
        // Do not hammer a backend returning an empty page with more expected.
        state.currentPage -= 1;
        autoMoreBlocked = true;
      }
    } else {
      state.items = nextItems;
      $('results').className = listingIsList() ? 'asset-list' : 'pack-grid';
      $('results').innerHTML = state.items.length ? (listingIsList() ? listColumnHeaders() : '') + listingMarkup(state.items)
        : '<div class="empty"><div class="empty-symbol">◇</div><strong>Nothing found</strong><p>Try another name, format, or category.</p></div>';
    }
    $('result-count').textContent = prettyNum(result.total);
    $('result-label').textContent = view === 'files' ? 'downloaded files' : 'assets found';
    $('load-more').hidden = state.items.length >= state.total || !state.items.length;
    $('load-more').textContent = `Load more (${prettyNum(state.items.length)} / ${prettyNum(state.total)}) ↓`;
  } catch (err) {
    if (id !== requestId) return;
    if (more) {
      state.currentPage -= 1;
      autoMoreBlocked = true;
      toast('Could not load more: ' + err.message);
    } else {
      $('results').innerHTML = `<div class="empty"><strong>Search unavailable</strong><p>${escapeHtml(err.message)}</p></div>`;
      $('load-more').hidden = true;
    }
  } finally {
    if (id === requestId) {
      listingBusy = false;
      // Also handles short result pages when the marker stays visible:
      // IntersectionObserver might not emit a second intersection event.
      requestAnimationFrame(checkAutoLoadMore);
    }
  }
}
function resetAssetDetails() {
  viewerToken++;
  if (closeFbxViewer) { closeFbxViewer(); closeFbxViewer = null; }
  state.selected = null;
  $('details-body').className = 'details-empty';
  $('details-body').innerHTML = '<div class="details-empty-icon">◇</div><strong>Nothing selected</strong><p>Select an asset to inspect its preview, source and metadata.</p>';
}
function openPanel() {
  if (state.page === 'assets' || state.page === 'pack') $('details-panel').classList.add('open');
}
function selectAsset(id) {
  if (state.page !== 'assets' && state.page !== 'pack') return;
  const a = state.items.find(x => x.id === id);
  if (!a) return;
  // Keep the Pack Explorer route, filters, active tab and pagination untouched.
  showAssetDetails(a);
}
function showAssetDetails(a) {
  if (state.page !== 'assets' && state.page !== 'pack') return;
  const id = a.id;
  viewerToken++; if (closeFbxViewer) { closeFbxViewer(); closeFbxViewer = null; }
  state.selected = { type: 'asset', id }; openPanel();
  const locationText = a.inner_path ? `${a.source_rel} :: ${a.inner_path}` : a.source_rel;
  const fallback = `<div class="preview-unavailable"><span>${icons[a.kind] || '◇'}</span>
    <p>Interactive preview is not available for this format.<br>Open the source in the matching asset editor.</p></div>`;
  const ext = a.ext.toLowerCase();
  let media = fallback;
  if (imageExt.has(ext)) media = `<img class="inspector-media" src="${previewUrl(a)}" alt="Preview of ${escapeHtml(a.name)}">`;
  else if (videoExt.has(ext)) media = `<video class="inspector-media" src="${previewUrl(a)}" controls preload="metadata"></video>`;
  else if (audioExt.has(ext)) media = `<div class="audio-preview">♫<audio src="${previewUrl(a)}" controls preload="none"></audio></div>`;
  else if (ext === '.obj') media = '<div class="model-preview"><canvas id="model-canvas" aria-label="Interactive OBJ wireframe preview"></canvas><span>Drag to rotate · OBJ wireframe</span></div>';
  else if (ext === '.fbx') media = '<div class="model-preview"><canvas id="fbx-canvas" aria-label="Interactive shaded FBX mesh preview"></canvas><span>Drag to rotate · Scroll to zoom · Static mesh only (no textures/animation)</span></div>';
  $('details-body').className = '';
  $('details-body').innerHTML = `<div class="details-content">
    <div class="inspector-preview">${media}</div>
    <div class="inspector-label">${escapeHtml(a.kind.toUpperCase())}</div>
    <h3 class="inspector-title">${escapeHtml(a.title || a.name)}</h3>
    <div class="inspector-sub">${escapeHtml(a.pack_name)}</div>
    <div class="details-tag-row">${pill(a.category, 'pink')}${pill(a.engine)}${pill(a.ext || 'file')}</div>
    <div class="inspector-divider"></div><div class="inspector-section-title">ASSET INFORMATION</div>
    <div class="inspector-metadata">
      <div class="meta-item"><label>Type</label><div>${escapeHtml(a.kind)}</div></div>
      <div class="meta-item"><label>Engine</label><div>${escapeHtml(a.engine)}</div></div>
      <div class="meta-item"><label>Location</label><div>${a.inner_path ? 'Inside archive' : 'On disk'}</div></div>
      <div class="meta-item"><label>Size</label><div>${a.bytes ? prettySize(a.bytes) : 'Not available'}</div></div>
    </div><div class="inspector-divider"></div><div class="inspector-section-title">SOURCE LOCATION</div>
    <div class="file-path">${escapeHtml(locationText)}</div>
    <p class="small-muted">${a.inner_path ? 'Located inside the original package archive; files are not extracted or modified.' : 'Located inside your local download folder.'}</p>
    <div class="inspector-actions">
      <button class="btn btn-primary" data-action="reveal" data-id="${escapeHtml(a.id)}">▣ Show source in Explorer</button>
      <button class="btn btn-outline" data-action="copy" data-text="${escapeHtml(locationText)}">Copy source path</button>
      <button class="btn btn-outline" data-action="select-pack" data-id="${escapeHtml(a.pack_id)}">Browse whole pack →</button>
    </div></div>`;
  document.querySelectorAll('.asset-card, .asset-list-row').forEach(el => el.classList.toggle('selected', el.dataset.id === id));
  if (ext === '.obj') startObjPreview(a, viewerToken);
  if (ext === '.fbx') startFbxPreview(a, viewerToken);
}

// FBX is decompressed and parsed on demand by the localhost server.
// The browser renders only normalized triangle geometry; full FBX animation,
// textures, materials and rigging are not reconstructed by this lightweight viewer.
async function startFbxPreview(asset, token) {
  const canvas = $('fbx-canvas');
  if (!canvas) return;
  try {
    const response = await fetch(`/api/fbx-geometry/${encodeURIComponent(asset.id)}`);
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try { message = (await response.json()).error || message; } catch { /* response was not JSON */ }
      throw Error(message);
    }
    const geometry = await response.json();
    if (viewerToken !== token || !canvas.isConnected) return;
    const module = await import('/fbx_viewer.js');
    if (viewerToken !== token || !canvas.isConnected) return;
    closeFbxViewer = module.startFbxViewer(canvas, geometry);
    if (geometry.truncated) toast('Large FBX: displaying a simplified mesh preview');
  } catch (err) {
    if (viewerToken === token && canvas.isConnected) canvas.parentElement.innerHTML =
      `<div class="preview-unavailable"><span>⬡</span><p>${escapeHtml(err.message)}</p></div>`;
  }
}

// Lightweight offline OBJ wireframe preview: no external JavaScript, shaders or CDN.
async function startObjPreview(a, token) {
  const canvas = $('model-canvas');
  if (!canvas) return;
  try {
    const response = await fetch(previewUrl(a));
    if (!response.ok) throw Error('OBJ file too large or unavailable');
    const text = await response.text();
    if (viewerToken !== token) return;
    const vertices = [], edges = [], seen = new Set();
    for (const line of text.split(/\r?\n/)) {
      if (vertices.length > 100000 || edges.length > 20000) break;
      const s = line.trim();
      if (s.startsWith('v ')) {
        const parts = s.slice(2).trim().split(/\s+/).slice(0, 3).map(Number);
        if (parts.length === 3 && parts.every(Number.isFinite)) vertices.push(parts);
      } else if (s.startsWith('f ')) {
        const face = s.slice(2).trim().split(/\s+/).map(x => Number(x.split('/')[0]));
        for (let i = 0; i < face.length && i < 30; i++) {
          const j = (i + 1) % face.length;
          const va = face[i] > 0 ? face[i] - 1 : vertices.length + face[i];
          const vb = face[j] > 0 ? face[j] - 1 : vertices.length + face[j];
          if (va < 0 || vb < 0 || va >= vertices.length || vb >= vertices.length) continue;
          const key = [Math.min(va, vb), Math.max(va, vb)].join(':');
          if (!seen.has(key)) { seen.add(key); edges.push([va, vb]); }
        }
      }
    }
    if (!vertices.length || !edges.length) throw Error('No renderable mesh in this OBJ');
    let min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
    vertices.forEach(v => v.forEach((n, k) => { min[k] = Math.min(min[k], n); max[k] = Math.max(max[k], n); }));
    const center = min.map((m, k) => (m + max[k]) / 2);
    const size = Math.max(...max.map((m, k) => m - min[k]), 0.001);
    const normalized = vertices.map(v => v.map((n, k) => (n - center[k]) / size));
    let rotX = -0.2, rotY = 0.7, dragging = false, oldX = 0, oldY = 0;
    canvas.addEventListener('pointerdown', e => { dragging = true; oldX = e.clientX; oldY = e.clientY; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener('pointerup', () => { dragging = false; });
    canvas.addEventListener('pointermove', e => {
      if (!dragging) return;
      rotY += (e.clientX - oldX) * 0.012; rotX += (e.clientY - oldY) * 0.012;
      oldX = e.clientX; oldY = e.clientY;
    });
    function draw() {
      if (viewerToken !== token || !canvas.isConnected) return;
      const ctx = canvas.getContext('2d'), w = canvas.clientWidth, h = canvas.clientHeight;
      if (!w || !h) return;
      canvas.width = Math.floor(w * Math.min(devicePixelRatio, 2));
      canvas.height = Math.floor(h * Math.min(devicePixelRatio, 2));
      ctx.scale(canvas.width / w, canvas.height / h);
      ctx.clearRect(0, 0, w, h);
      if (!dragging) rotY += 0.003;
      const cx = Math.cos(rotX), sx = Math.sin(rotX), cy = Math.cos(rotY), sy = Math.sin(rotY);
      const pts = normalized.map(([x, y, z]) => {
        const xx = x * cy + z * sy, zz = z * cy - x * sy;
        const yy = y * cx - zz * sx;
        return [(xx / (3 + zz * cx + y * sx)) * Math.min(w, h) * 2 + w / 2,
                (-yy / (3 + zz * cx + y * sx)) * Math.min(w, h) * 2 + h / 2];
      });
      ctx.beginPath();
      for (const [i, j] of edges) { ctx.moveTo(...pts[i]); ctx.lineTo(...pts[j]); }
      ctx.strokeStyle = '#e9a2d8'; ctx.lineWidth = 0.8; ctx.stroke();
      requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
  } catch (err) {
    if (viewerToken === token && canvas.isConnected) canvas.parentElement.innerHTML =
      `<div class="preview-unavailable"><span>⬡</span><p>${escapeHtml(err.message)}</p></div>`;
  }
}

// Extra Tools: searchable, filterable archive discovery and non-destructive extraction.
const archiveFormatLabels = {
  '.zip': 'ZIP (.zip)', '.unitypackage': 'Unity package (.unitypackage)',
  '.tar.gz': 'TAR.GZ (.tar.gz)', '.tgz': 'TGZ (.tgz)', '.tar': 'TAR (.tar)',
  '.gz': 'GZIP (.gz)', '.7z': '7-Zip (.7z)', '.rar': 'RAR (.rar)'
};
function getVisibleArchiveItems() {
  const query = $('archive-search').value.trim().toLocaleLowerCase();
  return archiveItems.filter(item => {
    const matchesName = !query || item.name.toLocaleLowerCase().includes(query);
    const matchesFormat = allArchiveFormatsSelected || selectedArchiveFormats.has(item.extension);
    const matchesExtractionState = !$('archive-unextracted-only').checked || !item.destination_exists;
    return matchesName && matchesFormat && matchesExtractionState;
  });
}
function renderArchiveFormatFilter(afterRefresh = false) {
  const formats = [...new Set(archiveItems.map(item => item.extension).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  availableArchiveFormats = formats;
  if (allArchiveFormatsSelected) {
    selectedArchiveFormats.clear();
  } else {
    for (const format of [...selectedArchiveFormats]) {
      if (!formats.includes(format)) selectedArchiveFormats.delete(format);
    }
    if (formats.length && formats.every(format => selectedArchiveFormats.has(format))) {
      allArchiveFormatsSelected = true;
      selectedArchiveFormats.clear();
    } else if (afterRefresh && selectedArchiveFormats.size === 0) {
      allArchiveFormatsSelected = true;
    }
  }
  $('archive-format-checkboxes').innerHTML = formats.map(format =>
    `<label class="archive-format-option"><input class="archive-format-check" type="checkbox" data-format="${escapeHtml(format)}" ${allArchiveFormatsSelected || selectedArchiveFormats.has(format) ? 'checked' : ''}> <span>${escapeHtml(archiveFormatLabels[format] || format)}</span></label>`
  ).join('');
  $('archive-format-all').checked = allArchiveFormatsSelected;
  $('archive-format-all').disabled = archiveExtractionBusy || formats.length === 0;
  $('archive-format-summary').textContent = !formats.length ? 'No formats available'
    : allArchiveFormatsSelected ? `All formats (${formats.length})`
    : `${selectedArchiveFormats.size} format${selectedArchiveFormats.size === 1 ? '' : 's'} selected`;
  $('archive-format-menu').classList.toggle('disabled', archiveExtractionBusy || formats.length === 0);
  $('archive-format-checkboxes').querySelectorAll('.archive-format-check').forEach(input => {
    input.disabled = archiveExtractionBusy;
  });
}
function handleArchiveFormatChange(event) {
  const target = event.target;
  if (target.id === 'archive-format-all') {
    allArchiveFormatsSelected = target.checked;
    selectedArchiveFormats.clear();
  } else if (target.matches('.archive-format-check')) {
    const format = target.dataset.format;
    if (allArchiveFormatsSelected) {
      allArchiveFormatsSelected = false;
      for (const available of availableArchiveFormats) selectedArchiveFormats.add(available);
    }
    if (target.checked) selectedArchiveFormats.add(format);
    else selectedArchiveFormats.delete(format);
    if (availableArchiveFormats.length && availableArchiveFormats.every(value => selectedArchiveFormats.has(value))) {
      allArchiveFormatsSelected = true;
      selectedArchiveFormats.clear();
    }
  } else {
    return;
  }
  renderArchiveFormatFilter(false);
  renderArchiveList();
}
function formatArchiveDate(value) {
  if (!value) return 'Never';
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return 'Unknown';
  return date.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  });
}
function updateArchiveSelectionControls() {
  const visible = getVisibleArchiveItems();
  const selectable = visible.filter(item => item.supported);
  const selectedCount = archiveItems.filter(item => selectedArchiveIds.has(item.id) && item.supported).length;
  const hiddenSelected = archiveItems.filter(item => selectedArchiveIds.has(item.id) && item.supported
    && !visible.some(shown => shown.id === item.id)).length;
  $('archive-selection-count').textContent = hiddenSelected
    ? `${prettyNum(selectedCount)} selected (${prettyNum(hiddenSelected)} hidden by filters)`
    : `${prettyNum(selectedCount)} selected`;
  $('extract-archives').disabled = archiveExtractionBusy || archiveListBusy || selectedCount === 0;
  $('extract-archives').textContent = archiveExtractionBusy ? 'Extracting archives…' : 'Extract archives';
  $('archives-refresh').disabled = archiveExtractionBusy || archiveListBusy;
  $('archive-search').disabled = archiveExtractionBusy;
  $('archive-unextracted-only').disabled = archiveExtractionBusy;
  $('archive-format-menu').classList.toggle('disabled', archiveExtractionBusy || availableArchiveFormats.length === 0);
  $('archive-format-all').disabled = archiveExtractionBusy || availableArchiveFormats.length === 0;
  $('archive-format-checkboxes').querySelectorAll('.archive-format-check').forEach(input => {
    input.disabled = archiveExtractionBusy;
  });
  const selectAll = $('archives-select-all');
  const selectedVisible = selectable.filter(item => selectedArchiveIds.has(item.id)).length;
  selectAll.disabled = archiveExtractionBusy || archiveListBusy || selectable.length === 0;
  selectAll.checked = selectable.length > 0 && selectedVisible === selectable.length;
  selectAll.indeterminate = selectedVisible > 0 && selectedVisible < selectable.length;
}
function archiveFolderHref(id) {
  return `/api/open-archive-folder?id=${encodeURIComponent(id || '')}`;
}
function archiveFolderLink(id, label, extraClass = '') {
  if (!id) return escapeHtml(label || '');
  const classes = `archive-file-link${extraClass ? ` ${extraClass}` : ''}`;
  return `<a class="${classes}" data-open-archive-folder href="${escapeHtml(archiveFolderHref(id))}" title="Open containing folder">${escapeHtml(label || '')}</a>`;
}
function renderArchiveLogMessage(entry) {
  const message = String(entry.message || '');
  const archiveName = String(entry.archive_name || '');
  if (!entry.archive_id || !archiveName) return escapeHtml(message);
  const index = message.indexOf(archiveName);
  if (index < 0) return escapeHtml(message);
  return `${escapeHtml(message.slice(0, index))}${archiveFolderLink(entry.archive_id, archiveName, 'archive-log-file-link')}${escapeHtml(message.slice(index + archiveName.length))}`;
}
function updateArchiveLogFilterButton(entries = archiveProgressEntries) {
  const button = $('archive-log-failures');
  if (!button) return;
  const failures = entries.filter(entry => entry.level === 'error').length;
  button.textContent = archiveLogFailuresOnly
    ? `Show all entries (${prettyNum(entries.length)})`
    : `Show failures only (${prettyNum(failures)})`;
  button.setAttribute('aria-pressed', String(archiveLogFailuresOnly));
}
function renderArchiveProgressLog(entries = archiveProgressEntries) {
  const log = $('archive-progress-log');
  archiveProgressEntries = entries;
  const visible = archiveLogFailuresOnly ? entries.filter(entry => entry.level === 'error') : entries;
  const lastEntry = entries.length ? entries[entries.length - 1] : null;
  const signature = `${archiveLogFailuresOnly ? 'failures' : 'all'}:${entries.length}:${lastEntry ? `${lastEntry.at || ''}:${lastEntry.message || ''}:${lastEntry.archive_id || ''}` : ''}`;
  updateArchiveLogFilterButton(entries);
  if (signature === archiveProgressLogSignature) return;
  if (archiveLogFailuresOnly && visible.length === 0) {
    log.innerHTML = '<div class="archive-progress-empty">No failures recorded for this extraction.</div>';
  } else {
    log.innerHTML = visible.map(entry => {
      const date = entry.at ? new Date(entry.at) : null;
      const timeLabel = date && !Number.isNaN(date.getTime()) ? date.toLocaleTimeString() : (entry.at || '');
      const level = ['success', 'warning', 'error'].includes(entry.level) ? entry.level : '';
      return `<div class="archive-progress-entry ${level}"><time datetime="${escapeHtml(entry.at || '')}">${escapeHtml(timeLabel)}</time><span>${renderArchiveLogMessage(entry)}</span></div>`;
    }).join('');
  }
  archiveProgressLogSignature = signature;
  log.scrollTop = log.scrollHeight;
}
function renderArchiveList() {
  const visible = getVisibleArchiveItems();
  const hasFilter = $('archive-search').value.trim() !== '' || !allArchiveFormatsSelected
    || $('archive-unextracted-only').checked;
  $('archive-count').textContent = hasFilter
    ? `${prettyNum(visible.length)} of ${prettyNum(archiveItems.length)} archives`
    : `${prettyNum(archiveItems.length)} archive${archiveItems.length === 1 ? '' : 's'} found`;
  const host = $('archive-list');
  if (!archiveItems.length) {
    host.innerHTML = '<div class="empty"><div class="empty-symbol">▤</div><strong>No archives found</strong><p>Download packages first, then refresh this list.</p></div>';
    updateArchiveSelectionControls();
    return;
  }
  if (!visible.length) {
    host.innerHTML = '<div class="empty"><div class="empty-symbol">⌕</div><strong>No matching archives</strong><p>Try another archive name or choose different formats.</p></div>';
    updateArchiveSelectionControls();
    return;
  }
  const groups = new Map();
  for (const item of visible) {
    const key = item.package || '(library root)';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  const groupMarkup = [...groups.entries()].map(([packageName, items]) => {
    const selectable = items.filter(item => item.supported);
    const selectedInGroup = selectable.filter(item => selectedArchiveIds.has(item.id)).length;
    const collapsed = collapsedArchivePackages.has(packageName);
    const rows = items.map(item => {
      const disabled = !item.supported || archiveExtractionBusy;
      const note = !item.supported
        ? '<span class="archive-row-note unsupported">Unsupported format</span>'
        : item.destination_exists ? '<span class="archive-row-note exists">Extraction folder exists · re-extraction compares files</span>' : '';
      const lastDate = formatArchiveDate(item.last_extracted_at);
      const dateTitle = item.last_extracted_at ? new Date(item.last_extracted_at).toLocaleString() :
        item.destination_exists ? 'Extraction folder exists, but no extraction date was recorded' : 'This archive has not been extracted by LocalDex';
      return `<div class="archive-row${!item.supported ? ' unsupported' : item.destination_exists ? ' already-extracted' : ''}">
        <input class="archive-select" type="checkbox" data-archive-id="${escapeHtml(item.id)}" ${selectedArchiveIds.has(item.id) ? 'checked' : ''} ${disabled ? 'disabled' : ''} aria-label="Select ${escapeHtml(item.name)}">
        <span class="archive-file"><strong title="${escapeHtml(item.name)}">${archiveFolderLink(item.id, item.name, 'archive-name-link')}</strong><small title="${escapeHtml(item.relative_path)}">${archiveFolderLink(item.id, item.relative_path, 'archive-path-link')}</small>${note}</span>
        <span class="archive-format">${escapeHtml(item.extension)}</span>
        <span class="archive-size">${prettySize(item.size)}</span>
        <span class="archive-last-extracted" title="${escapeHtml(dateTitle)}">${escapeHtml(lastDate === 'Never' && item.destination_exists ? 'Not recorded' : lastDate)}</span>
      </div>`;
    }).join('');
    return `<details class="archive-package-group" data-package="${escapeHtml(packageName)}" ${collapsed ? '' : 'open'}>
      <summary><span class="archive-group-chevron" aria-hidden="true">⌄</span><strong title="${escapeHtml(packageName)}">${escapeHtml(packageName)}</strong>
        <span class="archive-group-count">${prettyNum(items.length)} archive${items.length === 1 ? '' : 's'}</span>
        ${selectedInGroup ? `<span class="archive-group-selected">${prettyNum(selectedInGroup)} selected</span>` : ''}</summary>
      <div class="archive-group-table">
        <div class="archive-list-header"><span></span><span>Archive / source path</span><span>Format</span><span>Size</span><span>Last extraction</span></div>
        ${rows}
      </div>
    </details>`;
  }).join('');
  host.innerHTML = groupMarkup;
  host.querySelectorAll('.archive-row').forEach(row => {
    row.addEventListener('click', ev => {
      if (ev.target.closest('a, input, button, label')) return;
      const checkbox = row.querySelector('.archive-select');
      if (!checkbox || checkbox.disabled) return;
      checkbox.checked = !checkbox.checked;
      checkbox.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
  host.querySelectorAll('details.archive-package-group').forEach(group => {
    group.addEventListener('toggle', () => {
      if (group.open) collapsedArchivePackages.delete(group.dataset.package);
      else collapsedArchivePackages.add(group.dataset.package);
    });
  });
  updateArchiveSelectionControls();
}
async function refreshArchiveList() {
  if (archiveListBusy || archiveExtractionBusy) return;
  archiveListBusy = true;
  $('archive-list').innerHTML = archiveScanningLoadingMarkup('Scanning downloaded archives…');
  updateArchiveSelectionControls();
  try {
    const data = await api('/api/archives');
    archiveItems = Array.isArray(data.archives) ? data.archives : [];
    const present = new Set(archiveItems.map(item => item.id));
    for (const id of selectedArchiveIds) if (!present.has(id)) selectedArchiveIds.delete(id);
    renderArchiveFormatFilter(true);
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
    return `<div class="archive-result-row"><span class="archive-state ${cls}">${escapeHtml(item.status)}</span><span><strong>${archiveFolderLink(item.id, item.name || 'Archive', 'archive-result-file-link')}</strong><small>${escapeHtml(item.message || '')}</small></span></div>`;
  }).join('');
}
function appendClientArchiveLog(message, level = 'error') {
  const log = $('archive-progress-log');
  const row = document.createElement('div');
  row.className = `archive-progress-entry ${level}`;
  const time = document.createElement('time');
  time.textContent = new Date().toLocaleTimeString();
  const text = document.createElement('span');
  text.textContent = message;
  row.append(time, text);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}
function renderArchiveProgress(job) {
  $('archive-progress-panel').hidden = false;
  const total = Math.max(0, Number(job.total) || 0);
  const completed = Math.max(0, Math.min(total, Number(job.completed) || 0));
  const percent = Math.max(0, Math.min(100, Number(job.percent) || 0));
  $('archive-progress-percent').textContent = `${percent}%`;
  $('archive-progress-fill').style.width = `${percent}%`;
  $('archive-progress-track').setAttribute('aria-valuenow', String(percent));

  let summary = `${prettyNum(completed)} of ${prettyNum(total)} selected archives completed`;
  if (job.status === 'running' && job.current_archive) {
    summary += ` · Processing ${Math.min(completed + 1, total)} of ${prettyNum(total)}: ${job.current_archive}`;
  } else if (job.status === 'running' && completed < total) {
    summary += ' · Preparing the next archive…';
  }
  $('archive-progress-summary').innerHTML = job.status === 'running' && job.current_archive
    ? `${escapeHtml(`${prettyNum(completed)} of ${prettyNum(total)} selected archives completed · Processing ${Math.min(completed + 1, total)} of ${prettyNum(total)}: `)}${archiveFolderLink(job.current_archive_id, job.current_archive, 'archive-summary-file-link')}`
    : escapeHtml(summary);

  const entries = Array.isArray(job.log) ? job.log : [];
  renderArchiveProgressLog(entries);

  if (job.status === 'running') {
    $('archive-operation-status').innerHTML = job.current_archive
      ? `Extracting ${Math.min(completed + 1, total)} of ${total}: ${archiveFolderLink(job.current_archive_id, job.current_archive, 'archive-status-file-link')}`
      : `Extraction in progress: ${completed} of ${total} selected archives completed.`;
  } else if (job.status === 'completed' || job.status === 'completed_with_errors') {
    const counts = job.counts || {};
    $('archive-operation-status').textContent = `Extraction finished: ${prettyNum(counts.extracted || 0)} extracted/merged, ${prettyNum(counts.skipped || 0)} skipped, ${prettyNum(counts.failed || 0)} failed.`;
  } else if (job.status === 'failed') {
    const lastError = [...entries].reverse().find(entry => entry.level === 'error');
    $('archive-operation-status').textContent = `Extraction failed${lastError ? `: ${lastError.message}` : '.'}`;
  }
  renderArchiveResults(Array.isArray(job.results) ? job.results : []);
}
async function monitorArchiveExtraction(jobId) {
  let consecutiveErrors = 0;
  while (archiveExtractionJobId === jobId) {
    try {
      const job = await api(`/api/archive-extraction-progress?job_id=${encodeURIComponent(jobId)}`);
      consecutiveErrors = 0;
      renderArchiveProgress(job);
      if (job.status !== 'running') return job;
    } catch (err) {
      consecutiveErrors += 1;
      $('archive-operation-status').textContent = `Waiting for extraction progress… (${err.message})`;
      if (consecutiveErrors >= 10) throw err;
    }
    await new Promise(resolve => window.setTimeout(resolve, 450));
  }
  throw Error('Archive progress tracking was stopped.');
}
async function extractSelectedArchives() {
  const selectedItems = archiveItems.filter(item => selectedArchiveIds.has(item.id) && item.supported);
  const ids = selectedItems.map(item => item.id);
  const replaceExistingIds = selectedItems.filter(item => item.destination_exists).map(item => item.id);
  if (!ids.length || archiveExtractionBusy) return;
  let confirmation;
  if (replaceExistingIds.length) {
    confirmation = `At least one selected archive already has an extraction folder.\n\nIf you continue, Local Dex will compare the new extraction with the existing files:\n• Identical files will be kept unchanged.\n• If a file differs, the existing version will be kept as a timestamped backup (for example, model_20261027_153700.fbx), and the new version will use the original filename.\n• Files that are not present in the new archive will be kept. Nothing is deleted.\n\nContinue extracting ${ids.length} selected archive(s)?`;
  } else {
    confirmation = `Extract ${ids.length} selected archive(s)? Original archives will be preserved.`;
  }
  if (!window.confirm(confirmation)) return;

  archiveExtractionBusy = true;
  archiveExtractionJobId = null;
  $('archive-operation-details').hidden = true;
  $('archive-progress-panel').hidden = false;
  $('archive-progress-percent').textContent = '0%';
  $('archive-progress-fill').style.width = '0%';
  $('archive-progress-track').setAttribute('aria-valuenow', '0');
  $('archive-progress-summary').textContent = `0 of ${prettyNum(ids.length)} selected archives completed`;
  $('archive-progress-log').innerHTML = '';
  archiveProgressLogSignature = '';
  archiveProgressEntries = [];
  archiveLogFailuresOnly = false;
  updateArchiveLogFilterButton(archiveProgressEntries);
  $('archive-operation-status').textContent = `Starting extraction of ${prettyNum(ids.length)} selected archive(s)…`;
  renderArchiveList();
  try {
    const started = await post('/api/extract-archives', { ids, replace_existing_ids: replaceExistingIds });
    if (!started.job_id) throw Error('The server did not return an extraction job ID.');
    archiveExtractionJobId = started.job_id;
    const job = await monitorArchiveExtraction(started.job_id);
    const counts = job.counts || {};
    let summary;
    if (job.status === 'failed') {
      const lastError = [...(job.log || [])].reverse().find(entry => entry.level === 'error');
      summary = `Extraction failed${lastError ? `: ${lastError.message}` : '.'}`;
    } else {
      summary = `Extraction finished: ${prettyNum(counts.extracted || 0)} extracted/merged, ${prettyNum(counts.skipped || 0)} skipped, ${prettyNum(counts.failed || 0)} failed.`;
    }
    $('archive-operation-status').textContent = summary;
    renderArchiveResults(Array.isArray(job.results) ? job.results : []);
    selectedArchiveIds.clear();
    toast(summary);
    archiveExtractionBusy = false;
    archiveExtractionJobId = null;
    await refreshArchiveList();
  } catch (err) {
    $('archive-operation-status').textContent = `Extraction failed: ${err.message}`;
    appendClientArchiveLog(`Extraction failed: ${err.message}`, 'error');
    toast('Archive extraction failed: ' + err.message);
  } finally {
    archiveExtractionBusy = false;
    archiveExtractionJobId = null;
    updateArchiveSelectionControls();
    if (state.page === 'statistics') refreshExtractionStats();
  }
}

// Configuration operations always run locally via the Dex server, not in the browser.
let configFetching = false;
let configLastAssetEnd = null;
const operationNames = { install: 'Installation', downloads: 'Downloads sync', assets: 'Asset indexing' };
const stateLabels = { never: 'Not run', running: 'Running', waiting_input: 'Waiting for login',
  success: 'Success', failed: 'Failed', interrupted: 'Interrupted' };
function configDate(value) {
  if (!value) return 'Never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString();
}
function renderConfiguration(data) {
  const r = data.readiness;
  $('config-ready-dot').className = 'config-dot ' + (r.ready ? 'ready' : 'not-ready');
  $('config-ready-title').textContent = r.ready ? 'Downloader installed and ready' : 'Downloader requires setup';
  const missing = [];
  if (!r.downloader_found) missing.push('Downloader script missing');
  if (!r.python_installed) missing.push('Python environment missing');
  else if (!r.dependencies_ok) missing.push('Python dependencies missing');
  if (r.dependencies_ok && !r.chromium_installed) missing.push('Chromium missing');
  if (!r.config_exists) missing.push('config.yaml missing');
  else if (!r.config_valid) missing.push('Invalid configuration');
  else if (!r.library_matches) missing.push('Library path mismatch');
  else if (!r.credentials_configured) missing.push('Login email is not configured');
  $('config-ready-detail').textContent = r.ready ? 'Python, Playwright, Chromium and configuration validated.'
    : (r.error || missing.join(' · ') || 'Verify the local installation.');
  $('config-downloader-path').textContent = r.downloader_dir;
  $('config-library-path').textContent = r.library_dir;
  $('config-file-path').textContent = r.config_path;
  for (const action of ['install', 'downloads', 'assets']) {
    const entry = data.history[action];
    const badge = $(`${action}-state`);
    badge.textContent = stateLabels[entry.state] || entry.state;
    badge.className = `config-badge state-${entry.state}`;
    const observed = !entry.started_at && data.observed?.[action];
    $(`${action}-last`).textContent = observed ? `Last file activity: ${configDate(observed)} (result unknown)` :
      `Last run: ${configDate(entry.started_at)}` +
      (entry.finished_at ? ` · Ended: ${configDate(entry.finished_at)}` : '');
    const btn = document.querySelector(`[data-job="${action}"]`);
    btn.disabled = !!data.active || (action === 'downloads' && !r.ready) ||
      (action === 'install' && !r.installer_found);
  }
  $('config-current').textContent = data.active ? `${operationNames[data.active]} in progress` :
    'No operation in progress.';
  const auth = $('config-auth');
  auth.hidden = data.active !== 'downloads' || !data.input_stage;
  if (!auth.hidden) {
    const code = data.input_stage === 'code';
    $('config-auth-message').textContent = code ? 'Enter the verification code received by email' :
      'Finish authentication in Chromium, then continue';
    $('config-code').hidden = !code;
    $('config-send-code').textContent = code ? 'Submit code' : 'Continue';
    $('config-auth-help').textContent = code ?
      'Or leave the code blank if you enter it directly in Chromium.' :
      'Only continue after the Synty login is complete.';
  }
  const log = $('config-log');
  const pinned = log.scrollHeight - log.clientHeight - log.scrollTop < 35;
  const output = [...(data.log || [])];
  if (data.partial && data.partial.trim()) output.push(data.partial);
  log.textContent = output.length ? output.join('\n') : 'No recent operations in this session.';
  if (pinned) log.scrollTop = log.scrollHeight;
  const asset = data.history.assets;
  if (asset.state === 'success' && asset.finished_at && configLastAssetEnd !== asset.finished_at) {
    configLastAssetEnd = asset.finished_at;
    api('/api/catalog').then(catalog => {
      state.catalog = catalog;
      renderStats(); renderSidebar();
    }).catch(err => toast('Catalog reload failed: ' + err.message));
  }
}
async function refreshConfiguration(force = false) {
  if (state.page !== 'configuration' || configFetching) return;
  configFetching = true;
  try {
    renderConfiguration(await api('/api/configuration' + (force === true ? '?refresh=1' : '')));
  } catch (err) {
    $('config-ready-detail').textContent = 'Status unavailable: ' + err.message;
  } finally { configFetching = false; }
}
async function startConfigJob(action) {
  try {
    const headless = action === 'downloads' && $('download-headless').checked;
    await post('/api/configuration/start', { action, headless });
    toast(`${operationNames[action]} started`);
    await refreshConfiguration();
  } catch (err) { toast('Cannot start: ' + err.message); }
}
async function replyConfigPrompt() {
  const value = $('config-code').hidden ? '' : $('config-code').value.trim();
  try {
    await post('/api/configuration/reply', { code: value });
    $('config-code').value = '';
    await refreshConfiguration();
  } catch (err) { toast(err.message); }
}

function bind() {
  setSidebarCollapsed(document.documentElement.dataset.sidebarCollapsed === 'true');
  $('sidebar-toggle').addEventListener('click', () => {
    setSidebarCollapsed(document.documentElement.dataset.sidebarCollapsed !== 'true', true);
  });
  document.body.addEventListener('click', async ev => {
    const button = ev.target.closest('[data-action]');
    if (!button) return;
    const action = button.dataset.action, id = button.dataset.id;
    if (action === 'select-pack') return navigate('pack', id);
    if (action === 'back-packs') return navigate('packs');
    if (action === 'select-asset') return selectAsset(id);
    if (action === 'collection') {
      navigate('packs'); state.collection = button.dataset.name;
      return applyPage('packs');
    }
    if (action === 'pack-tab') {
      resetAssetDetails();
      $('details-panel').classList.remove('open');
      state.packTab = button.dataset.tab; clearFilters(false); showPackHeader(); applyPage('pack'); return;
    }
    if (action === 'reveal-pack-current') {
      try { await post('/api/reveal-pack', { id: state.pack }); toast('Opened pack folder'); }
      catch (err) { toast(err.message); }
      return;
    }
    if (action === 'copy-pack-path') {
      const pack = packById();
      if (pack) try { await navigator.clipboard.writeText(pack.folder); toast('Folder name copied'); }
      catch { toast('Clipboard not available'); }
      return;
    }
    if (action === 'reveal' || action === 'reveal-pack') {
      try {
        await post(action === 'reveal' ? '/api/reveal' : '/api/reveal-pack', { id });
        toast('Opened in file explorer');
      } catch (err) { toast(err.message); }
      return;
    }
    if (action === 'copy') {
      try { await navigator.clipboard.writeText(button.dataset.text || ''); toast('Copied to clipboard'); }
      catch { toast('Clipboard not available'); }
    }
  });
  document.body.addEventListener('error', ev => {
    if (ev.target.matches('.asset-thumb-image')) {
      ev.target.replaceWith(Object.assign(document.createElement('span'), { className: 'asset-kind-icon', textContent: '▧' }));
    } else if (ev.target.matches('.inspector-media')) {
      ev.target.replaceWith(Object.assign(document.createElement('div'), {
        className: 'preview-unavailable', textContent: 'Preview not available for this file.'
      }));
    }
  }, true);
  document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.page)));
  $('search-input').addEventListener('input', ev => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.search = ev.target.value.trim(); refresh(); }, 180);
  });
  ['collection-filter', 'kind-filter', 'category-filter', 'engine-filter'].forEach(id => $(id).addEventListener('change', filtersChanged));
  $('clear-filters').addEventListener('click', () => clearFilters());
  $('load-more').addEventListener('click', () => requestMore(false));
  $('asset-view-grid').addEventListener('click', () => applyAssetView('grid'));
  $('asset-view-list').addEventListener('click', () => applyAssetView('list'));
  initAutoLoadMore();
  initDetailsResize();
  $('close-details').addEventListener('click', () => { viewerToken++; if (closeFbxViewer) { closeFbxViewer(); closeFbxViewer = null; } $('details-panel').classList.remove('open'); });
  $('theme-toggle').addEventListener('click', toggleTheme);
  document.querySelectorAll('[data-job]').forEach(btn => btn.addEventListener('click', () => startConfigJob(btn.dataset.job)));
  $('config-send-code').addEventListener('click', replyConfigPrompt);
  $('config-code').addEventListener('keydown', ev => { if (ev.key === 'Enter') replyConfigPrompt(); });
  $('config-recheck').addEventListener('click', () => refreshConfiguration(true));
  $('archives-refresh').addEventListener('click', refreshArchiveList);
  $('archive-search').addEventListener('input', renderArchiveList);
  $('archive-unextracted-only').addEventListener('change', renderArchiveList);
  $('archive-format-options').addEventListener('change', handleArchiveFormatChange);
  $('archive-log-failures').addEventListener('click', () => {
    archiveLogFailuresOnly = !archiveLogFailuresOnly;
    archiveProgressLogSignature = '';
    renderArchiveProgressLog(archiveProgressEntries);
  });
  document.addEventListener('click', async ev => {
    const formatMenu = $('archive-format-menu');
    if (formatMenu && formatMenu.open && !formatMenu.contains(ev.target)) formatMenu.open = false;
    const link = ev.target.closest('a[data-open-archive-folder]');
    if (!link || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    if (link.dataset.opening === '1') return;
    link.dataset.opening = '1';
    try {
      await api(link.getAttribute('href'));
      toast('Opened containing folder');
    } catch (err) {
      toast(`Could not open archive folder: ${err.message}`);
    } finally {
      delete link.dataset.opening;
    }
  });
  $('archives-select-all').addEventListener('change', ev => {
    const visibleSelectable = getVisibleArchiveItems().filter(item => item.supported);
    if (ev.target.checked) visibleSelectable.forEach(item => selectedArchiveIds.add(item.id));
    else visibleSelectable.forEach(item => selectedArchiveIds.delete(item.id));
    renderArchiveList();
  });
  $('archive-list').addEventListener('change', ev => {
    const checkbox = ev.target.closest('.archive-select');
    if (!checkbox) return;
    if (checkbox.checked) selectedArchiveIds.add(checkbox.dataset.archiveId);
    else selectedArchiveIds.delete(checkbox.dataset.archiveId);
    renderArchiveList();
  });
  $('extract-archives').addEventListener('click', extractSelectedArchives);
  $('config-edit').addEventListener('click', async () => {
    try { await post('/api/configuration/open-file', {}); toast('Configuration opened in the text editor'); }
    catch (err) { toast(err.message); }
  });
  window.setInterval(refreshConfiguration, 2400);
  window.addEventListener('hashchange', routeFromHash);
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape') { viewerToken++; if (closeFbxViewer) { closeFbxViewer(); closeFbxViewer = null; } $('details-panel').classList.remove('open'); }
    if (ev.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
      ev.preventDefault(); $('search-input').focus();
    }
  });
}
async function boot() {
  try {
    assetViewMode = localStorage.getItem(ASSET_VIEW_KEY) === 'list' ? 'list' : 'grid';
    packViewMode = localStorage.getItem(PACK_VIEW_KEY) === 'list' ? 'list' : 'grid';
  } catch (_) { assetViewMode = 'grid'; packViewMode = 'grid'; }
  applyTheme(document.documentElement.dataset.theme);
  applyAssetView(assetViewMode, false);
  bind();
  try {
    const [catalog, session] = await Promise.all([api('/api/catalog'), api('/api/session')]);
    state.catalog = catalog; state.token = session.token;
    renderStats(); renderSidebar(); routeFromHash();
  } catch (err) {
    $('results').innerHTML = `<div class="empty"><div class="empty-symbol">!</div>
      <strong>Could not load catalog</strong><p>${escapeHtml(err.message)}. Try rebuilding the index.</p></div>`;
    toast('Cannot load local catalog');
  }
}
boot();
