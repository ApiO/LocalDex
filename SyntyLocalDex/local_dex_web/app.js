'use strict';

const state = {
  catalog: null, token: '', page: 'overview', search: '', collection: '', kind: '',
  category: '', engine: '', pack: '', packTab: 'assets', currentPage: 1,
  perPage: 48, total: 0, items: [], selected: null, busy: false
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

function renderSidebar() {
  $('side-pack-count').textContent = prettyNum(state.catalog.stats.packs);
  $('side-asset-count').textContent = prettyNum(state.catalog.stats.assets);
  const collections = state.catalog.stats.collections;
  $('sidebar-collections').innerHTML = Object.keys(collections).sort().map(name =>
    `<button class="nav-link ${state.page === 'packs' && state.collection === name ? 'active' : ''}"
      data-action="collection" data-name="${escapeHtml(name)}">
      <span class="side-collection-dot" style="background:${collectionColor[name] || '#8b90a0'}"></span>
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
  // Invalidate any in-flight asset search when navigating to the statistics page.
  if (isStatistics) ++requestId;
  $('statistics-view').hidden = !isStatistics;
  $('browse-view').hidden = isStatistics;
  $('pack-detail').hidden = !isPack;
  $('section-top').hidden = isPack;
  if (isPack) {
    if (!packById()) return navigate('packs');
    showPackHeader();
  } else {
    const descriptions = {
      overview: ['Your asset packs', 'A home for everything you have downloaded.'],
      packs: ['Browse asset packs', 'Find a pack by collection, name or theme.'],
      assets: ['Asset explorer', 'Find individual models, prefabs, textures and files inside archives.'],
      files: ['Downloaded files', 'Original archives and files stored in your library.'],
      statistics: ['Statistics', 'Packages, files, categories and disk usage.']
    };
    const [title, subtitle] = descriptions[page] || descriptions.overview;
    $('section-title').textContent = title; $('section-subtitle').textContent = subtitle;
  }
  document.querySelectorAll('[data-page]').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  const showAssetFilters = isPack ? state.packTab === 'assets' : (page === 'assets' || page === 'files');
  $('kind-filter').hidden = !showAssetFilters;
  $('category-filter').hidden = !showAssetFilters;
  $('engine-filter').hidden = !showAssetFilters;
  $('collection-filter').hidden = isPack;
  for (const key of ['collection', 'kind', 'category', 'engine']) $(`${key}-filter`).value = state[key];
  $('search-input').placeholder = isPack ? `Search within ${packById().name}...`
    : page === 'assets' ? 'Search models, names, file paths...'
      : page === 'files' ? 'Search downloaded file names...' : 'Search pack name, collection, theme...';
  renderSidebar();
  if (!isStatistics) refresh();
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
  const page = route ? 'pack' : ['overview', 'packs', 'assets', 'files', 'statistics']
    .includes(location.hash.slice(2)) ? location.hash.slice(2) : 'overview';
  const newPack = route ? route[1] : '';
  if (page !== state.page || newPack !== state.pack) {
    clearFilters(false); state.packTab = 'assets'; state.selected = null;
    $('details-panel').classList.remove('open');
  }
  state.pack = newPack;
  applyPage(page);
}
function filtersChanged() {
  for (const key of ['collection', 'kind', 'category', 'engine']) state[key] = $(`${key}-filter`).value;
  refresh();
}
function renderPacks() {
  ++requestId;
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
  const view = state.page === 'pack' ? state.packTab : state.page;
  $('filter-note').textContent = state.page === 'pack' ? '· This pack only' : '';
  if (!more) {
    state.currentPage = 1; state.items = [];
    $('results').innerHTML = '<div class="loading">Searching the local index…</div>';
  }
  const params = new URLSearchParams({ view, q: state.search, collection: state.collection,
    kind: state.kind, category: state.category, engine: state.engine,
    pack: state.page === 'pack' ? state.pack : '', page: state.currentPage, limit: state.perPage });
  try {
    const result = await api('/api/search?' + params);
    if (id !== requestId) return;
    state.total = result.total;
    state.items = more ? state.items.concat(result.items) : result.items;
    $('result-count').textContent = prettyNum(result.total);
    $('result-label').textContent = view === 'files' ? 'downloaded files' : 'assets found';
    $('results').className = 'pack-grid';
    $('results').innerHTML = state.items.length ? state.items.map(assetCard).join('')
      : '<div class="empty"><div class="empty-symbol">◇</div><strong>Nothing found</strong><p>Try another name, format, or category.</p></div>';
    $('load-more').hidden = state.items.length >= state.total;
    $('load-more').textContent = `Load more (${prettyNum(state.items.length)} / ${prettyNum(state.total)}) ↓`;
  } catch (err) {
    if (id !== requestId) return;
    $('results').innerHTML = `<div class="empty"><strong>Search unavailable</strong><p>${escapeHtml(err.message)}</p></div>`;
  }
}
function openPanel() { $('details-panel').classList.add('open'); }
function selectAsset(id) {
  const a = state.items.find(x => x.id === id);
  if (!a) return;
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
  document.querySelectorAll('.asset-card').forEach(el => el.classList.toggle('selected', el.dataset.id === id));
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

async function reindex() {
  if (state.busy) return;
  state.busy = true;
  $('sidebar-index-btn').disabled = true;
  $('sidebar-index-btn').textContent = 'Indexing…';
  toast('Rebuilding index. Large Unity packages can take some time.');
  try {
    const result = await post('/api/reindex', { deep_unity: true });
    state.catalog = await api('/api/catalog');
    renderStats(); renderSidebar(); state.selected = null; applyPage(state.page);
    toast(`Index refreshed: ${prettyNum(result.stats.assets)} assets available`);
  } catch (err) { toast('Indexing error: ' + err.message); }
  finally {
    state.busy = false;
    $('sidebar-index-btn').disabled = false;
    $('sidebar-index-btn').textContent = '↻   Rebuild index';
  }
}
function bind() {
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
  $('load-more').addEventListener('click', () => { state.currentPage++; refresh(true); });
  $('close-details').addEventListener('click', () => { viewerToken++; if (closeFbxViewer) { closeFbxViewer(); closeFbxViewer = null; } $('details-panel').classList.remove('open'); });
  $('sidebar-index-btn').addEventListener('click', reindex);
  window.addEventListener('hashchange', routeFromHash);
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape') { viewerToken++; if (closeFbxViewer) { closeFbxViewer(); closeFbxViewer = null; } $('details-panel').classList.remove('open'); }
    if (ev.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
      ev.preventDefault(); $('search-input').focus();
    }
  });
}
async function boot() {
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
