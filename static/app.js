/* 四川地形·自然旅游资源地图 · 前端 */
(function () {
  'use strict';

  const TILE_VER = window.TILE_VER || 'v1';

  const BASEMAPS = {
    hyps: {
      url: '/tiles/hyps/{z}/{x}/{y}.png?v=' + TILE_VER,
      maxNativeZoom: 13, maxZoom: 17,
      attr: '高程 <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noopener">Terrarium</a> · 分层设色与晕渲由本地服务实时渲染',
    },
    hillshade: {
      url: '/tiles/hillshade/{z}/{x}/{y}.png?v=' + TILE_VER,
      maxNativeZoom: 13, maxZoom: 17,
      attr: '山体晕渲 · 光源西北 315°/45° · 本地渲染',
    },
    osm: {
      url: '/tiles/osm/{z}/{x}/{y}.png',
      maxNativeZoom: 19, maxZoom: 19,
      attr: '底图 &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> 贡献者 · CyclOSM',
    },
    topo: {
      url: '/tiles/topo/{z}/{x}/{y}.png',
      maxNativeZoom: 19, maxZoom: 19,
      attr: '地形注记底图 &copy; Esri — World Topo Map（OSM 无关的国际地形图，作对照）',
    },
  };

  const PROVINCE_BOUNDS = [[26.05, 97.35], [34.32, 108.55]];

  const state = {
    map: null,
    base: null,
    baseKey: 'hyps',
    meta: null,
    cats: {},
    resources: [],
    labels: [],
    rivers: null,
    filterCat: null,
    query: '',
    sort: 'ele',
    selected: null,
    layers: { res: true, peak: true, water: true, river: true, landform: true },
    groups: {},
    markerById: new Map(),
    labelMarkers: [],
    profileMode: false,
    profilePoints: [],
    profileLayers: [],
    eleCache: new Map(),
    lastCursor: 0,
  };

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
  const fmt = (n) => (n == null || isNaN(n) ? '—' : Math.round(n).toLocaleString('zh-CN'));
  const tint = (hex, a) => {
    const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (!m) return 'rgba(0,0,0,.06)';
    return 'rgba(' + parseInt(m[1], 16) + ',' + parseInt(m[2], 16) + ',' + parseInt(m[3], 16) + ',' + a + ')';
  };

  /* ------------------------------------------------------------ 初始化 */
  function init() {
    state.map = L.map('map', {
      center: [30.6, 103.0],
      zoom: 7,
      zoomAnimation: true,
      minZoom: 5,
      maxZoom: 17,
      zoomControl: true,
      attributionControl: true,
      preferCanvas: true,
      zoomSnap: 0.25,
      wheelPxPerZoomLevel: 120,
    });
    state.map.zoomControl.setPosition('topleft');
    L.control.scale({ position: 'bottomright', imperial: false, maxWidth: 110 }).addTo(state.map);

    state.groups = {
      bndCasing: L.layerGroup().addTo(state.map),
      bnd: L.layerGroup().addTo(state.map),
      rivCasing: L.layerGroup().addTo(state.map),
      riv: L.layerGroup().addTo(state.map),
      landform: L.layerGroup().addTo(state.map),
      res: L.layerGroup().addTo(state.map),
      labels: L.layerGroup().addTo(state.map),
      cities: L.layerGroup().addTo(state.map),
    };
    if (!state.map.getPane('labelPane')) {
      const pane = state.map.createPane('labelPane');
      pane.style.zIndex = 460;
      pane.style.pointerEvents = 'none';
    }

    setBasemap('hyps');
    state.map.fitBounds(PROVINCE_BOUNDS, { padding: [16, 16], animate: false });
    bindUi();
    loadData();

    state.map.on('moveend zoomend', onViewChange);
    state.map.on('mousemove', onMouseMove);
    state.map.on('click', onMapClick);
    window.addEventListener('resize', debounce(drawProfile, 150));
  }

  function debounce(fn, wait) {
    let t = null;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), wait);
    };
  }

  /* ------------------------------------------------------------ 数据加载 */
  async function loadData() {
    try {
      const [meta, res, labels, rivers, boundary] = await Promise.all([
        fetch('/api/meta').then((r) => r.json()),
        fetch('/api/resources').then((r) => r.json()),
        fetch('/api/labels').then((r) => r.json()),
        fetch('/api/rivers').then((r) => r.json()),
        fetch('/api/boundary').then((r) => r.json()).catch(() => null),
      ]);
      state.meta = meta;
      state.cats = Object.fromEntries((meta.categories || []).map((c) => [c.key, c]));
      state.resources = res;
      state.labels = labels;
      state.rivers = rivers;
      state.boundary = boundary;
      renderStats();
      renderChips();
      buildRivers();
      buildBoundary();
      buildResourceMarkers();
      buildLandformLabels();
      buildCities();
      renderList();
      refreshLabels();
      const hash = location.hash.replace('#', '');
      if (hash && state.markerById.has(hash)) selectResource(hash, true);
      // ?basemap=hillshade|osm|topo 可直接指定底图，方便分享特定视图
      const wanted = (new URLSearchParams(location.search).get('basemap') || '').toLowerCase();
      if (wanted && BASEMAPS[wanted]) setBasemap(wanted);
    } catch (err) {
      console.error(err);
      $('#list').appendChild(el('li', 'item', '<div></div><div><div class="item-name">数据加载失败</div>' +
        '<div class="item-meta">请确认本地服务已启动</div></div><div></div>'));
    }
  }

  function renderStats() {
    const m = state.meta || {};
    $('#stat-res').textContent = m.total || '—';
    $('#stat-label').textContent = m.labels || '—';
    if (m.highest && m.highest.ele) {
      $('#stat-highest').textContent = fmt(m.highest.ele) + 'm';
      $('#stat-highest-name').textContent = m.highest.name || '最高峰';
    }
  }

  function renderChips() {
    const box = $('#chips');
    box.innerHTML = '';
    const all = el('button', 'chip is-active', '全部<span class="chip-n">' + state.resources.length + '</span>');
    all.type = 'button';
    all.dataset.cat = '';
    box.appendChild(all);
    (state.meta.categories || []).forEach((cat) => {
      const n = (state.meta.counts || {})[cat.key] || 0;
      const b = el('button', 'chip',
        '<i class="chip-dot" style="--c:' + cat.color + '"></i>' + esc(cat.name) +
        '<span class="chip-n">' + n + '</span>');
      b.type = 'button';
      b.dataset.cat = cat.key;
      b.title = cat.desc || '';
      b.style.setProperty('--c', cat.color);
      b.style.setProperty('--tint', tint(cat.color, 0.10));
      box.appendChild(b);
    });
    box.addEventListener('click', (ev) => {
      const btn = ev.target.closest('.chip');
      if (!btn) return;
      box.querySelectorAll('.chip').forEach((c) => c.classList.toggle('is-active', c === btn));
      state.filterCat = btn.dataset.cat || null;
      applyFilter();
    });
  }

  function filtered() {
    const q = state.query.trim().toLowerCase();
    let out = state.resources.filter((r) => {
      if (state.filterCat && r.cat !== state.filterCat) return false;
      if (!q) return true;
      return (r.name + r.city + (r.tags || []).join('') + (r.level || '')).toLowerCase().includes(q);
    });
    if (state.sort === 'ele') {
      out = out.slice().sort((a, b) => (b.ele || b.dem_ele || -1) - (a.ele || a.dem_ele || -1));
    } else {
      out = out.slice().sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));
    }
    return out;
  }

  function renderList() {
    const list = $('#list');
    const items = filtered();
    list.innerHTML = '';
    $('#list-title').textContent = (state.filterCat ? state.cats[state.filterCat].name : '全部资源') +
      ' · ' + items.length;
    if (!items.length) {
      list.appendChild(el('li', 'item', '<div></div><div><div class="item-name">没有匹配的资源</div>' +
        '<div class="item-meta">换个关键词或分类试试</div></div><div></div>'));
      return;
    }
    const frag = document.createDocumentFragment();
    items.forEach((r) => {
      const cat = state.cats[r.cat] || { color: '#888', name: r.cat };
      const li = el('li', 'item', '');
      li.dataset.id = r.id;
      li.style.setProperty('--c', cat.color);
      if (state.selected === r.id) li.classList.add('is-active');
      const bar = el('i', 'item-bar');
      const mid = el('div', '', '<div class="item-name">' + esc(r.name) + '</div>' +
        '<div class="item-meta">' + esc(cat.name) + (r.city && r.city !== '—' ? ' · ' + esc(r.city) : '') +
        (r.level ? ' · ' + esc(r.level) : '') + '</div>');
      const eleVal = r.ele || r.dem_ele;
      const right = el('div', 'item-ele', eleVal ? fmt(eleVal) + '<small> m</small>' : '');
      li.append(bar, mid, right);
      li.addEventListener('click', () => selectResource(r.id, false));
      frag.appendChild(li);
    });
    list.appendChild(frag);
  }

  function applyFilter() {
    renderList();
    buildResourceMarkers();
    buildLandformLabels();
    refreshLabels();
  }

  /* ------------------------------------------------------------ 底图 */
  function setBasemap(key) {
    const cfg = BASEMAPS[key];
    if (!cfg) return;
    if (state.base) state.map.removeLayer(state.base);
    state.base = L.tileLayer(cfg.url, {
      maxZoom: cfg.maxZoom,
      maxNativeZoom: cfg.maxNativeZoom || cfg.maxZoom,
      minZoom: 5,
      attribution: cfg.attr,
      crossOrigin: false,
      keepBuffer: 2,
      updateWhenIdle: false,
      detectRetina: false,
    }).addTo(state.map);
    state.baseKey = key;
    state.base.bringToBack();
    document.querySelectorAll('.seg').forEach((b) => b.classList.toggle('is-active', b.dataset.base === key));
    document.body.dataset.basemap = key;
    refreshLabels();
  }

  /* ------------------------------------------------------------ 省界 */
  function buildBoundary() {
    if (!state.boundary || !state.boundary.features || !state.boundary.features.length) return;
    L.geoJSON(state.boundary, {
      interactive: false,
      style: () => ({ color: '#ffffff', weight: 5, opacity: 0.7, lineJoin: 'round' }),
    }).addTo(state.groups.bndCasing);
    L.geoJSON(state.boundary, {
      interactive: false,
      style: () => ({ color: '#46564d', weight: 1.5, opacity: 0.6 }),
    }).addTo(state.groups.bnd);
  }

  /* ------------------------------------------------------------ 河流 */
  function buildRivers() {
    if (!state.rivers || !state.rivers.features) return;
    state.groups.rivCasing.clearLayers();
    state.groups.riv.clearLayers();
    const color = '#3f93c4';
    L.geoJSON(state.rivers, {
      interactive: false,
      style: () => ({ color: '#ffffff', weight: 4.4, opacity: 0.75, lineCap: 'round' }),
    }).eachLayer((l) => state.groups.rivCasing.addLayer(l));
    L.geoJSON(state.rivers, {
      interactive: false,
      style: () => ({ color: color, weight: 2.1, opacity: 0.85, lineCap: 'round' }),
    }).eachLayer((l) => state.groups.riv.addLayer(l));
    applyRiverStyle();
  }

  function applyRiverStyle() {
    const z = state.map ? state.map.getZoom() : 7;
    const w = z <= 6 ? 1.2 : z <= 7 ? 1.7 : z <= 9 ? 2.3 : 3.0;
    state.groups.riv.eachLayer((l) => l.setStyle({ weight: w }));
    state.groups.rivCasing.eachLayer((l) => l.setStyle({ weight: w + 2.2 }));
  }

  /* ------------------------------------------------------------ 资源点 */
  function buildResourceMarkers() {
    if (!state.map) return;
    state.groups.res.clearLayers();
    state.groups.landform.clearLayers();
    state.markerById.clear();
    const items = filtered();
    items.forEach((r) => {
      const cat = state.cats[r.cat] || { color: '#888' };
      if (r.cat === 'landform') {
        state.markerById.set(r.id, null);
        return;
      }
      const big = r.cat === 'heritage' || r.cat === 'scenic';
      const icon = L.divIcon({
        className: '',
        html: '<div class="res-marker' + (big ? ' is-lg' : '') + '" style="--c:' + cat.color + '"></div>',
        iconSize: [big ? 13 : 11, big ? 13 : 11],
        iconAnchor: [big ? 6.5 : 5.5, big ? 6.5 : 5.5],
      });
      const mk = L.marker([r.lat, r.lon], { icon, title: r.name, riseOnHover: true });
      mk.on('click', (ev) => {
        L.DomEvent.stopPropagation(ev);
        selectResource(r.id, false);
      });
      mk.addTo(state.groups.res);
      state.markerById.set(r.id, mk);
    });
    applyLayerVisibility();
  }

  /* ------------------------------------------------------------ 注记 */
  const KIND_LAYER = { peak: 'peak', ridge: 'peak', glacier: 'peak', lake: 'water', river: 'water', park: 'peak' };

  function refreshLabels() {
    if (!state.map) return;
    state.groups.labels.clearLayers();
    state.labelMarkers = [];
    const z = state.map.getZoom();
    const bounds = state.map.getBounds();
    const pane = state.map.getPane('labelPane');
    const cellSize = 84;
    const grid = new Set();
    const taken = (x, y, w, h) => {
      const x0 = Math.floor(x / cellSize), x1 = Math.floor((x + w) / cellSize);
      const y0 = Math.floor(y / cellSize), y1 = Math.floor((y + h) / cellSize);
      for (let i = x0; i <= x1; i++) {
        for (let j = y0; j <= y1; j++) if (grid.has(i + ':' + j)) return true;
      }
      return false;
    };
    const take = (x, y, w, h) => {
      const x0 = Math.floor(x / cellSize), x1 = Math.floor((x + w) / cellSize);
      const y0 = Math.floor(y / cellSize), y1 = Math.floor((y + h) / cellSize);
      for (let i = x0; i <= x1; i++) {
        for (let j = y0; j <= y1; j++) grid.add(i + ':' + j);
      }
    };

    // 市州驻地先占位，避免山峰注记压在城市名上
    if (state.meta) {
      (state.meta.cities || []).forEach((c) => {
        const need = c.rank === 1 ? 5.5 : c.rank === 2 ? 7 : 8.5;
        if (z < need || !bounds.contains([c.lat, c.lon])) return;
        const p = state.map.latLngToContainerPoint([c.lat, c.lon]);
        take(p.x - c.name.length * 7 - 6, p.y - 9, c.name.length * 14 + 12, 18);
      });
    }

    const candidates = state.labels.filter((l) => {
      if (l.minZoom > z + 0.01) return false;
      if (!bounds.contains([l.lat, l.lon])) return false;
      const layer = KIND_LAYER[l.kind] || 'peak';
      return !!state.layers[layer];
    });
    candidates.sort((a, b) => {
      const ia = (a.ele || 0) * 10 - (a.kind === 'park' ? 40000 : 0);
      const ib = (b.ele || 0) * 10 - (b.kind === 'park' ? 40000 : 0);
      return ib - ia;
    });

    let count = 0;
    for (const item of candidates) {
      if (count >= 110) break;
      const p = state.map.latLngToContainerPoint([item.lat, item.lon]);
      const big = item.kind === 'peak' && (item.ele || 0) >= 5500;
      const w = item.name.length * (big ? 12 : 10.5) + 8;
      const h = item.kind === 'park' ? 14 : (item.ele ? 24 : 15);
      if (taken(p.x - w / 2, p.y - h / 2, w, h)) continue;
      take(p.x - w / 2, p.y - h / 2, w, h);

      const cls = item.kind === 'lake' ? 'water-label'
        : item.kind === 'river' ? 'river-label'
          : item.kind === 'park' ? 'park-label'
            : 'peak-label' + (big ? ' big' : '');
      const inner = item.kind === 'peak' && item.ele
        ? esc(item.name) + '<span class="pe">' + fmt(item.ele) + '</span>'
        : esc(item.name);
      const icon = L.divIcon({
        className: '',
        html: '<div class="' + cls + '">' + inner + '</div>',
        iconSize: [0, 0], iconAnchor: [0, 0],
      });
      const mk = L.marker([item.lat, item.lon], {
        icon, interactive: false, keyboard: false, pane: pane ? 'labelPane' : undefined,
      });
      state.groups.labels.addLayer(mk);
      state.labelMarkers.push(mk);
      count++;
    }
  }

  function applyLayerVisibility() {
    const toggle = (group, on) => {
      if (!state.map) return;
      if (on && !state.map.hasLayer(group)) group.addTo(state.map);
      if (!on && state.map.hasLayer(group)) state.map.removeLayer(group);
    };
    toggle(state.groups.res, state.layers.res);
    toggle(state.groups.riv, state.layers.river);
    toggle(state.groups.rivCasing, state.layers.river);
    toggle(state.groups.labels, state.layers.peak || state.layers.water);
    toggle(state.groups.landform, state.layers.landform && state.layers.res);
  }

  // 地貌区大字：只在中低缩放级别出现，避免和资源点抢注意力
  function buildLandformLabels() {
    if (!state.map) return;
    state.groups.landform.clearLayers();
    const z = state.map.getZoom();
    if (!state.layers.landform || !state.layers.res || z > 9.5) return;
    filtered().forEach((r) => {
      if (r.cat !== 'landform') return;
      if (!state.map.getBounds().contains([r.lat, r.lon])) return;
      const icon = L.divIcon({
        className: '',
        html: '<div class="landform-label">' + esc(r.name) + '</div>',
        iconSize: [0, 0], iconAnchor: [0, 0],
      });
      state.groups.landform.addLayer(L.marker([r.lat, r.lon], {
        icon, interactive: false, keyboard: false, pane: 'labelPane',
      }));
    });
  }

  // 市州驻地：给地形图提供空间参照
  function buildCities() {
    if (!state.map || !state.groups.cities || !state.meta) return;
    const g = state.groups.cities;
    g.clearLayers();
    const z = state.map.getZoom();
    const bounds = state.map.getBounds();
    (state.meta.cities || []).forEach((c) => {
      const need = c.rank === 1 ? 5.5 : c.rank === 2 ? 7 : 8.5;
      if (z < need || !bounds.contains([c.lat, c.lon])) return;
      const icon = L.divIcon({
        className: '',
        html: '<div class="city-label r' + c.rank + '">' + esc(c.name) + '</div>',
        iconSize: [0, 0], iconAnchor: [0, 0],
      });
      g.addLayer(L.marker([c.lat, c.lon], {
        icon, interactive: false, keyboard: false, pane: 'labelPane',
      }));
    });
  }

  function onViewChange() {
    applyRiverStyle();
    refreshLabels();
    buildLandformLabels();
    buildCities();
    applyLayerVisibility();
  }

  /* ------------------------------------------------------------ 详情 */
  async function selectResource(id, fly) {
    state.selected = id;
    const r = state.resources.find((x) => x.id === id);
    if (!r) return;
    document.querySelectorAll('.item').forEach((li) => li.classList.toggle('is-active', li.dataset.id === id));
    document.querySelectorAll('.res-marker').forEach((m) => m.classList.remove('is-active'));
    const active = document.querySelector('.item.is-active');
    if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' });
    const mk = state.markerById.get(id);
    if (mk && mk.getElement()) {
      const dot = mk.getElement().querySelector('.res-marker');
      if (dot) dot.classList.add('is-active');
    }
    if (fly && r.cat !== 'landform') {
      state.map.flyTo([r.lat, r.lon], Math.max(state.map.getZoom(), 9.2), { duration: 0.7 });
    }
    history.replaceState(null, '', '#' + id);
    openDetail(r);
  }

  function openDetail(r) {
    const detail = $('#detail');
    detail.hidden = false;
    const cat = state.cats[r.cat] || { name: r.cat, color: '#888' };
    $('#detail-cat').textContent = cat.name;
    $('#detail-cat').style.setProperty('--c', cat.color);
    $('#detail-cat').style.setProperty('--tint', tint(cat.color, 0.12));
    $('#detail-name').textContent = r.name;
    $('#detail-meta').textContent = [r.city && r.city !== '—' ? r.city : '', r.level || '']
      .filter(Boolean).join(' · ') || '四川';
    const tags = $('#detail-tags');
    tags.innerHTML = '';
    (r.tags || []).forEach((t) => tags.appendChild(el('span', '', esc(t))));
    $('#detail-intro').textContent = r.intro || '';
    $('#detail-terrain').innerHTML = '<div class="terrain-cell"><b>' +
      (r.ele || r.dem_ele ? fmt(r.ele || r.dem_ele) + ' m' : '—') +
      '</b><span>' + (r.ele ? '峰顶/标称高程' : 'DEM 采样高程') + '</span></div>' +
      '<div class="terrain-cell"><b>…</b><span>周边起伏</span></div>' +
      '<div class="terrain-cell"><b>' + (r.lat.toFixed(2)) + '°N</b><span>' +
      r.lon.toFixed(2) + '°E</span></div>';
    $('#detail-near').innerHTML = '';
    $('#ai-text').textContent = '';
    $('#ai-btn').disabled = false;
    $('#ai-btn').dataset.rid = r.id;

    fetch('/api/resource/' + encodeURIComponent(r.id)).then((x) => x.json()).then((data) => {
      if (state.selected !== r.id) return;
      const t = data.terrain;
      const cells = document.querySelectorAll('#detail-terrain .terrain-cell');
      if (t && cells.length >= 2) {
        cells[1].innerHTML = '<b>' + fmt(t.relief) + ' m</b><span>±' +
          t.radius_km + ' km 高差（' + fmt(t.min) + '–' + fmt(t.max) + '）</span>';
      }
      const near = $('#detail-near');
      if (data.nearby && data.nearby.length) {
        const kindName = { peak: '山峰', ridge: '山脊', lake: '湖泊', river: '河流', glacier: '冰川' };
        near.innerHTML = '<h3>相关地形注记</h3>';
        data.nearby.slice(0, 5).forEach((n) => {
          near.appendChild(el('div', 'near-row',
            '<span>' + esc(n.name) + ' <i>' + (kindName[n.kind] || '') + '</i></span>' +
            '<i>' + n.dist_km + ' km' + (n.ele ? ' · ' + fmt(n.ele) + ' m' : '') + '</i>'));
        });
      }
      if (data.note) {
        $('#ai-text').innerHTML = esc(data.note.text) + '<span class="src">来源：' +
          (data.note.source === 'deepseek' ? 'DeepSeek' : '本地地形规则') + '（已缓存）</span>';
      }
    }).catch(() => {});
  }

  function closeDetail() {
    $('#detail').hidden = true;
    state.selected = null;
    document.querySelectorAll('.item').forEach((li) => li.classList.remove('is-active'));
    document.querySelectorAll('.res-marker').forEach((m) => m.classList.remove('is-active'));
    history.replaceState(null, '', location.pathname + location.search);
  }

  /* ------------------------------------------------------------ 剖面 */
  function onMapClick(ev) {
    if (!state.profileMode) return;
    const { lat, lng } = ev.latlng;
    if (state.profilePoints.length >= 12) return;
    state.profilePoints.push([lat, lng]);
    drawProfileGeometry();
    if (state.profilePoints.length >= 2) requestProfile();
    else $('#profile-hint').textContent = '再点一个点即可生成剖面';
  }

  function drawProfileGeometry() {
    state.profileLayers.forEach((l) => state.map.removeLayer(l));
    state.profileLayers = [];
    if (!state.profilePoints.length) return;
    if (state.profilePoints.length > 1) {
      state.profileLayers.push(L.polyline(state.profilePoints, {
        color: '#1f7a5c', weight: 2.4, opacity: 0.9, dashArray: '6 5',
      }).addTo(state.map));
    }
    state.profilePoints.forEach((p, i) => {
      state.profileLayers.push(L.circleMarker(p, {
        radius: 4, color: '#fff', weight: 1.6, fillColor: '#1f7a5c', fillOpacity: 1,
      }).bindTooltip(String(i + 1), { permanent: false }).addTo(state.map));
    });
  }

  async function requestProfile() {
    $('#profile-hint').textContent = '正在沿路径采样高程…';
    try {
      const resp = await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ points: state.profilePoints }),
      });
      const data = await resp.json();
      if (data.error) {
        $('#profile-hint').textContent = data.error;
        return;
      }
      state.profileData = data;
      drawProfile();
      const s = data.stats || {};
      $('#profile-hint').textContent = state.profilePoints.length + ' 个点 · ' +
        (s.length_km || 0) + ' km';
      $('#profile-stats').innerHTML =
        '<span>最低 <b>' + fmt(s.min) + ' m</b></span>' +
        '<span>最高 <b>' + fmt(s.max) + ' m</b></span>' +
        '<span>累计爬升差值 <b>' + fmt(s.relief) + ' m</b></span>' +
        '<span>水平长度 <b>' + (s.length_km || 0) + ' km</b></span>';
    } catch (err) {
      $('#profile-hint').textContent = '采样失败，请重试';
    }
  }

  function drawProfile() {
    const data = state.profileData;
    const canvas = $('#profile-canvas');
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const W = Math.max(rect.width, 320);
    const H = 132;
    canvas.width = W * ratio;
    canvas.height = H * ratio;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (!data || !data.points || data.points.length < 2) return;

    const pts = data.points.filter((p) => p.ele != null);
    if (pts.length < 2) return;
    const pad = { l: 40, r: 8, t: 8, b: 18 };
    const maxD = pts[pts.length - 1].dist_km || 1;
    let minE = Math.min.apply(null, pts.map((p) => p.ele));
    let maxE = Math.max.apply(null, pts.map((p) => p.ele));
    const span = Math.max(maxE - minE, 200);
    minE = Math.floor((minE - span * 0.08) / 100) * 100;
    maxE = Math.ceil((maxE + span * 0.12) / 100) * 100;

    const x = (d) => pad.l + (d / maxD) * (W - pad.l - pad.r);
    const y = (e) => pad.t + (1 - (e - minE) / (maxE - minE)) * (H - pad.t - pad.b);

    // 网格
    ctx.strokeStyle = '#eef1ee';
    ctx.lineWidth = 1;
    const steps = 4;
    ctx.font = '9px -apple-system, "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#8b978f';
    for (let i = 0; i <= steps; i++) {
      const e = minE + ((maxE - minE) * i) / steps;
      const py = y(e);
      ctx.beginPath();
      ctx.moveTo(pad.l, py);
      ctx.lineTo(W - pad.r, py);
      ctx.stroke();
      ctx.textAlign = 'right';
      ctx.fillText(Math.round(e) + 'm', pad.l - 5, py + 3);
    }

    // 面积
    const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
    grad.addColorStop(0, 'rgba(31,122,92,.34)');
    grad.addColorStop(1, 'rgba(31,122,92,.03)');
    ctx.beginPath();
    ctx.moveTo(x(pts[0].dist_km), H - pad.b);
    pts.forEach((p) => ctx.lineTo(x(p.dist_km), y(p.ele)));
    ctx.lineTo(x(pts[pts.length - 1].dist_km), H - pad.b);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // 线条
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(x(p.dist_km), y(p.ele)) : ctx.moveTo(x(p.dist_km), y(p.ele))));
    ctx.strokeStyle = '#1f7a5c';
    ctx.lineWidth = 1.8;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // 最高点标注
    const peak = pts.reduce((a, b) => (b.ele > a.ele ? b : a), pts[0]);
    ctx.beginPath();
    ctx.arc(x(peak.dist_km), y(peak.ele), 3, 0, Math.PI * 2);
    ctx.fillStyle = '#1f7a5c';
    ctx.fill();
    ctx.fillStyle = '#16211c';
    ctx.textAlign = 'center';
    ctx.fillText(Math.round(peak.ele) + ' m', x(peak.dist_km), y(peak.ele) - 6);

    // 横轴
    ctx.fillStyle = '#8b978f';
    ctx.textAlign = 'left';
    ctx.fillText('0', pad.l, H - 5);
    ctx.textAlign = 'right';
    ctx.fillText(maxD.toFixed(0) + ' km', W - pad.r, H - 5);
  }

  /* ------------------------------------------------------------ 光标高程 */
  const onMouseMove = debounce(function (ev) {
    const { lat, lng } = ev.latlng;
    $('#cursor-coord').textContent = lng.toFixed(3) + '°E  ' + lat.toFixed(3) + '°N';
    const key = lat.toFixed(2) + ',' + lng.toFixed(2);
    if (state.eleCache.has(key)) {
      showEle(state.eleCache.get(key));
      return;
    }
    const inProvince = lat >= PROVINCE_BOUNDS[0][0] && lat <= PROVINCE_BOUNDS[1][0] &&
      lng >= PROVINCE_BOUNDS[0][1] && lng <= PROVINCE_BOUNDS[1][1];
    if (!inProvince) {
      showEle(null);
      return;
    }
    fetch('/api/elevation?lat=' + lat.toFixed(4) + '&lon=' + lng.toFixed(4))
      .then((r) => r.json())
      .then((d) => {
        state.eleCache.set(key, d.ele);
        showEle(d.ele);
      })
      .catch(() => showEle(null));
  }, 180);

  function showEle(ele) {
    $('#cursor-ele').textContent = ele == null ? '海拔 —' : '海拔 ' + fmt(ele) + ' m';
  }

  /* ------------------------------------------------------------ UI 绑定 */
  function bindUi() {
    $('#basemap').addEventListener('click', (ev) => {
      const btn = ev.target.closest('.seg');
      if (btn) setBasemap(btn.dataset.base);
    });

    $('#layers').addEventListener('click', (ev) => {
      const btn = ev.target.closest('.layer');
      if (!btn) return;
      const key = btn.dataset.layer;
      state.layers[key] = !state.layers[key];
      btn.classList.toggle('is-active', state.layers[key]);
      if (key === 'landform' || key === 'res') buildLandformLabels();
      refreshLabels();
      applyLayerVisibility();
    });

    const search = $('#search');
    search.addEventListener('input', debounce(() => {
      state.query = search.value;
      $('#search-clear').hidden = !state.query;
      applyFilter();
    }, 180));
    $('#search-clear').addEventListener('click', () => {
      search.value = '';
      state.query = '';
      $('#search-clear').hidden = true;
      applyFilter();
    });

    document.querySelectorAll('.sort-btn').forEach((b) => {
      b.addEventListener('click', () => {
        document.querySelectorAll('.sort-btn').forEach((x) => x.classList.toggle('is-active', x === b));
        state.sort = b.dataset.sort;
        renderList();
      });
    });

    $('#detail-close').addEventListener('click', closeDetail);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (state.profileMode) toggleProfile(false);
        else closeDetail();
      }
    });

    $('#ai-btn').addEventListener('click', async (ev) => {
      const btn = ev.currentTarget;
      const rid = btn.dataset.rid;
      if (!rid) return;
      btn.disabled = true;
      $('#ai-text').textContent = '正在结合地形数据生成解读…';
      try {
        const resp = await fetch('/api/ai/interpret', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rid }),
        });
        const data = await resp.json();
        $('#ai-text').innerHTML = esc(data.text || '暂无结果') +
          '<span class="src">来源：' + (data.source === 'deepseek' ? 'DeepSeek' : '本地地形规则') +
          (data.cached ? '（缓存）' : '') + '</span>';
      } catch (err) {
        $('#ai-text').textContent = '生成失败，请稍后重试。';
      }
      btn.disabled = false;
    });

    $('#reset-view').addEventListener('click', () => {
      state.map.flyToBounds(PROVINCE_BOUNDS, { padding: [12, 12], duration: 0.6 });
    });

    $('#profile-btn').addEventListener('click', () => toggleProfile());
    $('#profile-close').addEventListener('click', () => toggleProfile(false));
    $('#profile-clear').addEventListener('click', () => {
      state.profilePoints = [];
      state.profileData = null;
      drawProfileGeometry();
      drawProfile();
      $('#profile-stats').innerHTML = '';
      $('#profile-hint').textContent = '在地图上依次点击 2–12 个点';
    });

    $('#side-toggle').addEventListener('click', () => $('#side').classList.add('is-open'));
    $('#side-close').addEventListener('click', () => $('#side').classList.remove('is-open'));
    $('#side').addEventListener('click', (e) => {
      if (window.innerWidth <= 900 && e.target.closest('.item')) {
        $('#side').classList.remove('is-open');
      }
    });
  }

  function toggleProfile(force) {
    state.profileMode = force == null ? !state.profileMode : force;
    $('#profile-btn').classList.toggle('is-active', state.profileMode);
    $('#profile-panel').hidden = !state.profileMode;
    if (state.profileMode) {
      state.map.getContainer().style.cursor = 'crosshair';
      if (!state.profilePoints.length) $('#profile-hint').textContent = '在地图上依次点击 2–12 个点';
      setTimeout(drawProfile, 60);
    } else {
      state.map.getContainer().style.cursor = '';
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
