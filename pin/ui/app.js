// Pin UI. Talks to Python through window.pywebview.api; Python pushes updates back
// by calling App.on(event, payload).
(function () {
  const ICONS = {
    folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9L9.6 3.6A2 2 0 0 0 8.2 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeoff: '<path d="M9.9 4.2A10 10 0 0 1 12 4c6.5 0 10 8 10 8a17 17 0 0 1-2.2 3.2M6.6 6.6C3.9 8.4 2 12 2 12s3.5 8 10 8a9.7 9.7 0 0 0 5.4-1.6"/><path d="M14.1 14.1a3 3 0 1 1-4.2-4.2"/><path d="m2 2 20 20"/>',
    alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    download: '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M4 20h16"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    play: '<path d="M7 4v16l13-8z"/>',
    expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    left: '<path d="m15 18-6-6 6-6"/>',
    right: '<path d="m9 18 6-6-6-6"/>',
    home: '<path d="m3 10 9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
    rss: '<path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/>',
    lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  };
  const icon = (n) => `<svg class="i" viewBox="0 0 24 24">${ICONS[n] || ''}</svg>`;
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const MARK = (size) => `<span class="mark" style="--size:${size}px"><span class="l">p</span><span class="mi"><span class="c"><b></b><b></b><b></b></span><span class="c"><b></b><b></b><b></b></span><span class="c"><b></b><b></b></span></span><span class="l">n</span></span>`;
  function hydrateIcons(root) {
    (root || document).querySelectorAll('[data-icon]').forEach((el) => {
      const svg = icon(el.dataset.icon);
      el.removeAttribute('data-icon');
      if (el.tagName === 'I') el.outerHTML = svg; else el.insertAdjacentHTML('afterbegin', svg);
    });
  }
  hydrateIcons();

  let api = null;
  let settings = {}, upd = null, modal = null, home = '', platform = 'darwin';
  let pins = [];                  // [{id, t, hidden}] newest first
  const thumbs = new Map();       // id -> {src, ratio, w, h}
  const tiles = new Map();        // id -> element
  const fresh = new Set();
  const sel = new Set();
  let view = 'pins', busy = false, cfg = null, saverSt = null, access = true;
  const tilde = (p) => (home && p && p.startsWith(home) ? '~' + p.slice(home.length) : p);
  const visible = () => pins.filter((p) => (view === 'hidden' ? p.hidden : !p.hidden));

  // ---------- toasts ----------
  function toast(text, err, action) {
    const t = document.createElement('div');
    t.className = 'toast' + (err ? ' err' : '');
    t.innerHTML = icon(err ? 'alert' : 'check') + `<span>${esc(text)}</span>`;
    if (action) {
      const b = document.createElement('button');
      b.textContent = action.label;
      b.onclick = action.run;
      t.appendChild(b);
    }
    $('#toasts').appendChild(t);
    setTimeout(() => { t.style.transition = 'opacity .3s'; t.style.opacity = 0; setTimeout(() => t.remove(), 300); }, 4200);
  }

  // ---------- state from Python ----------
  async function load() {
    const st = await api.state();
    access = st.access;
    saverSt = st.saver;
    renderSaver();
    if (!access) { renderAccess(); return; }
    $('#access').classList.add('hidden');
    $('#grid').classList.remove('hidden');
    cfg = st.config;
    renderSource();
    pins = st.pins;
    busy = st.busy;
    renderBusy();
    for (const id of [...tiles.keys()]) if (!pins.find((p) => p.id === id)) tiles.delete(id);
    layout();
    loadThumbs();
  }

  // ---------- thumbnails ----------
  let thumbQueue = Promise.resolve();
  function loadThumbs() {
    const need = pins.filter((p) => !thumbs.has(p.id)).map((p) => p.id);
    if (!need.length) return;
    thumbQueue = thumbQueue.then(async () => {
      for (let i = 0; i < need.length; i += 16) {
        const batch = need.slice(i, i + 16).filter((id) => !thumbs.has(id));
        if (!batch.length) continue;
        const res = await api.thumbs(batch);
        for (const id of batch) {
          const r = res[id];
          if (r) thumbs.set(id, r);
          else { pins = pins.filter((p) => p.id !== id); tiles.delete(id); } // unreadable file: drop it
        }
        layoutSoon();
      }
    });
  }

  // ---------- masonry ----------
  let layoutTimer = 0;
  function layoutSoon() { clearTimeout(layoutTimer); layoutTimer = setTimeout(layout, 60); }

  function tileEl(p) {
    let el = tiles.get(p.id);
    if (el) return el;
    el = document.createElement('div');
    el.className = 'tile';
    el.dataset.id = p.id;
    el.innerHTML = `<img alt=""><div class="shade"></div><span class="check">${icon('check')}</span>
      <div class="tacts">
        <button data-a="save" title="Save image">${icon('download')}</button>
        <button data-a="hide" title="">${icon('eyeoff')}</button>
        <button data-a="open" title="View">${icon('expand')}</button>
      </div>`;
    el.addEventListener('animationend', (e) => { if (e.animationName === 'tile-in') el.style.animation = 'none'; });
    tiles.set(p.id, el);
    return el;
  }

  function layout() {
    const grid = $('#grid');
    const list = visible().filter((p) => thumbs.has(p.id));
    $('#n-pins').textContent = pins.filter((p) => !p.hidden).length;
    $('#n-hidden').textContent = pins.filter((p) => p.hidden).length;
    const width = grid.clientWidth - 36;
    const n = Math.max(2, Math.min(7, Math.round(width / 240)));
    const colW = (width - (n - 1) * 12) / n;
    const cols = [];
    const heights = new Array(n).fill(0);
    for (let i = 0; i < n; i++) { const c = document.createElement('div'); c.className = 'col'; cols.push(c); }
    for (const p of list) {
      const th = thumbs.get(p.id);
      const h = colW * Math.min(Math.max(th.ratio || 1.3, .45), 2.6);
      let k = 0;
      for (let i = 1; i < n; i++) if (heights[i] < heights[k] - 1) k = i;
      heights[k] += h + 12;
      const el = tileEl(p);
      el.style.height = h + 'px';
      const img = el.querySelector('img');
      if (!img.src) { img.onload = () => img.classList.add('ok'); img.src = th.src; }
      el.classList.toggle('sel', sel.has(p.id));
      el.classList.toggle('fresh', fresh.has(p.id));
      const hb = el.querySelector('[data-a="hide"]');
      hb.title = p.hidden ? 'Show in the screensaver again' : 'Hide from the screensaver';
      hb.innerHTML = icon(p.hidden ? 'eye' : 'eyeoff');
      cols[k].appendChild(el);
    }
    const holder = $('#cols');
    holder.replaceChildren(...cols);
    renderEmpty(list.length);
    renderSel();
  }
  window.addEventListener('resize', layoutSoon);

  function renderEmpty(count) {
    const e = $('#empty');
    if (count || !access) { e.classList.add('hidden'); return; }
    const loading = pins.some((p) => !thumbs.has(p.id));
    if (loading) { e.classList.add('hidden'); return; }
    e.classList.remove('hidden');
    if (view === 'hidden') {
      e.innerHTML = `<div class="logomark lg">${MARK(30)}</div><h3>Nothing hidden</h3>
        <p>Hide a pin and the screensaver skips it for good.<br>Hidden pins land here, so you can bring them back.</p>`;
    } else {
      e.innerHTML = `<div class="logomark lg">${MARK(30)}</div><h3>${busy ? 'Fetching your pins…' : 'No pins yet'}</h3>
        <p>${busy ? 'They appear here as they download.' : `Pin pulls pins from <b>${esc(cfg ? cfg.source : 'Pinterest')}</b> for your screensaver.`}</p>
        ${busy ? '' : `<button class="btn-primary" data-e="refresh">${icon('refresh')}Get pins</button>`}`;
      const b = e.querySelector('[data-e="refresh"]');
      if (b) b.onclick = () => refresh(false);
    }
  }

  // ---------- selection ----------
  function renderSel() {
    const n = sel.size;
    document.body.classList.toggle('selecting', n > 0);
    $('#selbar').classList.toggle('hidden', n === 0);
    $('#select-all').classList.toggle('hidden', n > 0);
    $('#save-all').classList.toggle('hidden', n > 0 || view === 'hidden');
    $('#sel-count').textContent = `${n} selected`;
    $('#sel-hide').querySelector('span').textContent = view === 'hidden' ? 'Show again' : 'Hide';
    $('#sel-hide').querySelector('svg').outerHTML = icon(view === 'hidden' ? 'eye' : 'eyeoff');
  }
  function toggleSel(id) { sel.has(id) ? sel.delete(id) : sel.add(id); const el = tiles.get(id); if (el) el.classList.toggle('sel', sel.has(id)); renderSel(); }
  function clearSel() { sel.clear(); tiles.forEach((el) => el.classList.remove('sel')); renderSel(); }

  // ---------- actions ----------
  async function save(ids, choose) {
    if (!ids.length) return;
    const r = await api.save_pins(ids, !!choose);
    if (!r) return;
    if (choose) { settings.save_dir = r.dir; renderSavePath(); }
    if (r.saved) toast(r.saved === 1 ? 'Saved to ' + tilde(r.dir) : `Saved ${r.saved} pins to ${tilde(r.dir)}`, false,
      { label: 'Show', run: () => (r.saved === 1 ? api.reveal_saved(r.last) : api.open_save_dir()) });
    else toast("Couldn't save those pins", true);
  }

  async function setHidden(ids, hidden) {
    if (!ids.length) return;
    const r = await api.set_hidden(ids, hidden);
    if (!r.ok) { if (r.access === false) load(); return; }
    const set = new Set(ids);
    const gone = [];
    pins.forEach((p) => { if (set.has(p.id)) { p.hidden = hidden; const el = tiles.get(p.id); if (el) gone.push(el); } });
    ids.forEach((id) => sel.delete(id));
    gone.forEach((el) => { el.style.animation = ''; el.classList.add('gone'); });
    setTimeout(() => { gone.forEach((el) => { el.classList.remove('gone'); el.style.animation = 'none'; }); layout(); }, 280);
    toast(hidden ? (ids.length === 1 ? 'Hidden from the screensaver' : `${ids.length} pins hidden from the screensaver`)
      : (ids.length === 1 ? 'Back in the screensaver' : `${ids.length} pins back in the screensaver`), false,
      { label: 'Undo', run: () => setHidden(ids, !hidden) });
    if (cfg) cfg.hiddenCount = r.hiddenCount;
  }

  function refresh(startOver) {
    if (busy) return;
    if (startOver) {
      showModal('startover', `
        <div class="modal-title"><h2>Start over?</h2></div>
        <p style="color:var(--text2);line-height:1.5">This drops the pins Pin and the screensaver have cached for <b>${esc(cfg ? cfg.source : '')}</b>
        and downloads a fresh set. Hidden pins stay hidden, and images you saved stay where they are.</p>
        <div class="foot"><button class="btn-quiet" data-m="close">Cancel</button><button class="btn-primary inline" data-m="go">${icon('refresh')}Start over</button></div>`,
        (m) => {
          closeModal();
          if (m === 'go') { thumbs.clear(); tiles.clear(); pins = pins.filter((p) => p.hidden); layout(); go(true); }
        });
      return;
    }
    go(false);
    async function go(so) { busy = true; renderBusy(); renderEmpty(visible().length); await api.refresh(so); }
  }

  function renderBusy() {
    const b = $('#refresh-btn');
    b.classList.toggle('busy', busy);
    b.querySelector('span').textContent = busy ? 'Fetching pins…' : 'Refresh pins';
  }

  // ---------- sidebar ----------
  function renderSource() {
    if (!cfg) return;
    $('#source-icon').innerHTML = icon(cfg.home ? 'home' : 'rss');
    $('#source-name').textContent = cfg.source;
    $('#source-kind').textContent = cfg.home ? 'Signed in with your session cookie' : 'Public feed or board';
    $('#speed').value = cfg.speed; $('#speed-val').textContent = Math.round(cfg.speed) + ' pt/s';
    $('#tile').value = cfg.tile; $('#tile-val').textContent = Math.round(cfg.tile) + ' pt';
    $('#opt-clock .switch').classList.toggle('on', !!cfg.clock);
    $('#opt-24h .switch').classList.toggle('on', !!cfg.clock24h);
    $('#opt-24h').style.opacity = cfg.clock ? 1 : .45;
  }

  function renderSaver() {
    const s = saverSt || {};
    const dot = $('#saver-dot');
    const btn = $('#saver-install');
    dot.className = 'dot';
    if (!s.installed) {
      $('#saver-title').textContent = 'Screensaver not installed';
      $('#saver-sub').textContent = s.old ? 'Replaces the old Pinterest Saver' : 'Install it to use your pins as a screensaver';
      btn.querySelector('span').textContent = 'Install';
      dot.classList.add('warn');
    } else if (!s.current) {
      $('#saver-title').textContent = 'Screensaver update ready';
      $('#saver-sub').textContent = `Installed ${s.installed}, this app has ${s.bundled}`;
      btn.querySelector('span').textContent = 'Update';
      dot.classList.add('warn');
    } else {
      $('#saver-title').textContent = 'Screensaver installed';
      $('#saver-sub').textContent = platform === 'darwin' ? 'Pick Pin in Screen Saver settings' : (s.active === false ? 'Not selected in Screen Saver settings' : 'Selected as your screensaver');
      btn.querySelector('span').textContent = 'Settings';
      dot.classList.add('ok');
    }
    btn.disabled = !s.bundled && !s.installed;
  }

  function renderSavePath() { $('#save-path').textContent = tilde(settings.save_dir || ''); }

  function renderAccess() {
    $('#grid').classList.add('hidden');
    $('#empty').classList.add('hidden');
    const a = $('#access');
    a.classList.remove('hidden');
    a.innerHTML = `<div class="card">
      <div class="logomark lg">${MARK(30)}</div>
      <h3>Let Pin reach the screensaver's pins</h3>
      <p>macOS keeps the screensaver's pins and settings inside its own sandbox. When macOS asks whether
      <b>Pin</b> may access data from other apps, click <b>Allow</b>. If you said no before, turn Pin on in
      Privacy &amp; Security, then try again.</p>
      <div class="row2"><button class="btn-quiet" data-a="privacy">Open Privacy &amp; Security</button><button class="btn-primary" data-a="retry">${icon('refresh')}Try again</button></div>
    </div>`;
    a.onclick = async (e) => {
      const b = e.target.closest('[data-a]');
      if (!b) return;
      if (b.dataset.a === 'privacy') api.open_privacy();
      else { await api.check_access(); load(); }
    };
  }

  let cfgTimer = 0;
  function setCfg(key, value, delay) {
    clearTimeout(cfgTimer);
    cfgTimer = setTimeout(async () => {
      const r = await api.set_config(key, value);
      if (r && r.error === 'access') load();
      else if (r && !r.error) { cfg = r; renderSource(); }
    }, delay || 0);
  }

  // ---------- viewer ----------
  let vIndex = -1, vList = [];
  async function openViewer(id) {
    vList = visible().filter((p) => thumbs.has(p.id));
    vIndex = vList.findIndex((p) => p.id === id);
    if (vIndex < 0) return;
    renderViewer();
  }
  async function renderViewer() {
    const p = vList[vIndex];
    const v = $('#viewer');
    v.classList.remove('hidden');
    const th = thumbs.get(p.id) || {};
    v.innerHTML = `<div class="vtop pywebview-drag-region">
        <span class="meta">${vIndex + 1} of ${vList.length}${th.w ? ` · ${th.w} × ${th.h}` : ''}</span>
        <button class="btn-quiet" data-v="save">${icon('download')}Save</button>
        <button class="btn-quiet" data-v="saveas">${icon('folder')}Save to…</button>
        <button class="btn-quiet" data-v="copy">${icon('copy')}Copy</button>
        <button class="btn-quiet" data-v="hide">${icon(p.hidden ? 'eye' : 'eyeoff')}${p.hidden ? 'Show again' : 'Hide'}</button>
        <button class="btn-icon filled" data-v="close" title="Close (Esc)">${icon('x')}</button>
      </div>
      <div class="stage"><img src="${th.src}" alt="">
        ${vIndex > 0 ? `<button class="nav prev" data-v="prev">${icon('left')}</button>` : ''}
        ${vIndex < vList.length - 1 ? `<button class="nav next" data-v="next">${icon('right')}</button>` : ''}
      </div>`;
    const img = v.querySelector('.stage img');
    const want = p.id;
    api.full(p.id).then((r) => { if (vList[vIndex] && vList[vIndex].id === want && r) img.src = r.src; }).catch(() => {});
  }
  function closeViewer() { $('#viewer').classList.add('hidden'); $('#viewer').innerHTML = ''; vIndex = -1; }
  $('#viewer').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-v]');
    if (!b) { if (e.target.classList.contains('stage')) closeViewer(); return; }
    const p = vList[vIndex];
    switch (b.dataset.v) {
      case 'close': closeViewer(); break;
      case 'prev': vIndex--; renderViewer(); break;
      case 'next': vIndex++; renderViewer(); break;
      case 'save': save([p.id]); break;
      case 'saveas': save([p.id], true); break;
      case 'copy': toast((await api.copy_pin(p.id)) ? 'Copied' : "Couldn't copy that one", false); break;
      case 'hide': {
        await setHidden([p.id], !p.hidden);
        vList.splice(vIndex, 1);
        if (!vList.length) closeViewer();
        else { vIndex = Math.min(vIndex, vList.length - 1); renderViewer(); }
      }
    }
  });
  document.addEventListener('keydown', (e) => {
    if (vIndex >= 0) {
      if (e.key === 'Escape') closeViewer();
      else if (e.key === 'ArrowLeft' && vIndex > 0) { vIndex--; renderViewer(); }
      else if (e.key === 'ArrowRight' && vIndex < vList.length - 1) { vIndex++; renderViewer(); }
      return;
    }
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'Escape') { if (modal) closeModal(); else clearSel(); }
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === 'r') { e.preventDefault(); refresh(false); }
    if (mod && e.key.toLowerCase() === 'a') { e.preventDefault(); visible().forEach((p) => sel.add(p.id)); layout(); }
  });

  // ---------- modals ----------
  function closeModal() { $('#modal-root').innerHTML = ''; modal = null; }
  function showModal(name, html, onClick, cls) {
    const box = modal === name && $('#modal-root .modal');
    modal = name;
    if (box) { box.className = `modal ${cls || ''}`; box.innerHTML = html; }
    else $('#modal-root').innerHTML = `<div class="modal-back"><div class="modal ${cls || ''}">${html}</div></div>`;
    $('#modal-root .modal-back').onclick = (e) => {
      if (e.target.classList.contains('modal-back')) return closeModal();
      const el = e.target.closest('[data-m]');
      if (el) onClick(el.dataset.m, el);
    };
  }

  function openSource() {
    const home = cfg && cfg.home;
    showModal('source', `
      <div class="modal-title"><h2>Where pins come from</h2><button class="btn-icon" data-m="close">${icon('x')}</button></div>
      <div class="tabs" id="src-tabs">
        <button data-m="tab" data-t="feed" class="${home ? '' : 'on'}">${icon('rss')}Public feed or board</button>
        <button data-m="tab" data-t="home" class="${home ? 'on' : ''}">${icon('home')}My home feed</button>
      </div>
      <div id="src-body"></div>`,
      async (m, el) => {
        if (m === 'close') closeModal();
        else if (m === 'tab') {
          document.querySelectorAll('#src-tabs button').forEach((b) => b.classList.toggle('on', b === el));
          sourceBody(el.dataset.t);
        } else if (m === 'save-feed') {
          const v = $('#feed-in').value.trim();
          if (cfg.home) await api.set_cookie('');
          const r = await api.set_config('feed', v);
          if (r && r.error) { $('#feed-err').textContent = r.error === 'access' ? "Pin can't reach the screensaver's settings." : r.error; return; }
          cfg = r; closeModal(); sourceChanged();
        } else if (m === 'connect') {
          const v = $('#cookie-in').value.trim();
          if (!v) { $('#cookie-err').textContent = 'Paste the _pinterest_sess value first.'; return; }
          const r = await api.set_cookie(v);
          if (r && r.error) { $('#cookie-err').textContent = "Pin can't reach the screensaver's settings."; return; }
          cfg = r; closeModal(); sourceChanged();
        } else if (m === 'disconnect') {
          const r = await api.set_cookie('');
          if (r && !r.error) { cfg = r; closeModal(); sourceChanged(); }
        } else if (m === 'pinterest') api.open_url('https://www.pinterest.com/');
      });
    sourceBody(home ? 'home' : 'feed');
  }
  function sourceBody(tab) {
    const b = $('#src-body');
    if (tab === 'feed') {
      b.innerHTML = `<div class="field">
          <div class="label">Pinterest username, username/board, or a board link</div>
          <div class="inline-row"><input id="feed-in" spellcheck="false" placeholder="e.g. nasa or nasa/space" value="${esc(cfg && !cfg.home ? cfg.feed : '')}">
          <button class="btn-primary inline" data-m="save-feed">Use this</button></div>
          <span class="err" id="feed-err"></span>
          <span class="hint">Reads Pinterest's public RSS feed, so there's no sign-in. The profile or board has to be public.</span>
        </div>`;
      setTimeout(() => $('#feed-in') && $('#feed-in').focus(), 30);
    } else {
      b.innerHTML = `<div class="field">
          ${cfg && cfg.home ? `<div style="display:flex;align-items:center;gap:10px"><span class="pill-ok">${icon('check')}Connected</span><span class="hint" style="flex:1">Showing your own home feed.</span><button class="btn-quiet" data-m="disconnect">Disconnect</button></div><div class="label" style="margin-top:6px">Paste a new cookie if it expired</div>` : '<div class="label">Your _pinterest_sess cookie</div>'}
          <div class="inline-row"><input id="cookie-in" type="password" spellcheck="false" autocomplete="off" placeholder="Paste the value">
          <button class="btn-primary inline" data-m="connect">${icon('lock')}Connect</button></div>
          <span class="err" id="cookie-err"></span>
          <ol class="steps">
            <li>Sign in at <a href="#" data-m="pinterest" style="color:var(--accent)">pinterest.com</a> in your browser.</li>
            <li>Open the developer tools (${platform === 'darwin' ? '<code>⌥⌘I</code>' : '<code>F12</code>'}) and go to <b>Application</b> (Chrome, Edge) or <b>Storage</b> (Safari, Firefox) → <b>Cookies</b>.</li>
            <li>Copy the value of <code>_pinterest_sess</code> and paste it above.</li>
          </ol>
          <span class="hint">The cookie stays on this computer in the screensaver's settings and is only ever sent to pinterest.com.
          It lasts weeks to months; signing out of Pinterest in that browser ends it.</span>
        </div>`;
      setTimeout(() => $('#cookie-in') && $('#cookie-in').focus(), 30);
    }
  }
  function sourceChanged() {
    renderSource();
    thumbs.clear(); tiles.clear(); sel.clear(); pins = [];
    load().then(() => { if (!pins.length) refresh(false); });
  }

  // ---------- settings & updates (shared with Tag/Dwn) ----------
  const sw = (on) => `<span class="switch ${on ? 'on' : ''}"></span>`;
  const opt = (key, title, detail) => `<button class="opt" data-m="toggle" data-key="${key}"><div class="t"><b>${title}</b><span>${detail}</span></div>${sw(settings[key])}</button>`;
  const ago = (iso) => {
    if (!iso) return 'Never checked';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return 'Checked just now';
    if (s < 3600) return `Checked ${Math.round(s / 60)} min ago`;
    if (s < 86400) return `Checked ${Math.round(s / 3600)} h ago`;
    return 'Checked ' + new Date(iso).toLocaleDateString();
  };
  function updateLine() {
    if (!upd) return ['', ''];
    switch (upd.phase) {
      case 'checking': return ['Checking for updates…', ''];
      case 'uptodate': return ["You're up to date", 'ok'];
      case 'available': return [`Version ${upd.latest} is available`, 'ok'];
      case 'downloading': return [`Downloading ${upd.latest}… ${Math.round(upd.progress * 100)}%`, ''];
      case 'ready': return [`Version ${upd.latest} is ready to install`, 'ok'];
      case 'installing': return ['Installing…', ''];
      case 'failed': return [upd.error || 'Update failed', 'bad'];
      default: return [ago(upd.last_checked), ''];
    }
  }
  function renderUpdateRow() {
    const el = $('#upd-row');
    if (!el) return;
    const [line, cls] = updateLine();
    const has = upd && ['available', 'downloading', 'ready'].includes(upd.phase);
    el.innerHTML = `<div class="t"><b>Pin ${esc(upd ? upd.current : '')}</b><span class="${cls}">${esc(line)}</span></div>
      ${has ? `<button class="btn-quiet" data-m="see-update">${icon('download')}See update</button>` : `<button class="btn-quiet" data-m="check" ${upd && upd.phase === 'checking' ? 'disabled' : ''}>${icon('refresh')}Check now</button>`}`;
  }
  function openSettings() {
    showModal('settings', `
      <div class="modal-title"><h2>Settings</h2><button class="btn-icon" data-m="close">${icon('x')}</button></div>
      <div class="label">Saving</div>
      <div class="group"><div class="ver-row"><div class="t"><b>Saved pins go to</b><span>${esc(tilde(settings.save_dir || ''))}</span></div>
        <button class="btn-quiet" data-m="savedir">${icon('folder')}Change</button></div></div>
      <div class="label">Screensaver</div>
      <div class="group"><div class="ver-row"><div class="t"><b>${esc($('#saver-title').textContent)}</b><span>${esc($('#saver-sub').textContent)}</span></div>
        <button class="btn-quiet" data-m="saver-settings">${icon('monitor')}Screen Saver settings</button></div></div>
      <div class="label">Updates</div>
      <div class="group">
        <div class="ver-row" id="upd-row"></div>
        ${opt('auto_check', 'Check for updates automatically', 'Looks for a new version at launch and every few hours')}
        ${opt('auto_install', 'Download and install updates automatically', 'Downloads in the background and installs when you quit. The screensaver updates with it.')}
      </div>
      <div class="label">About</div>
      <div class="about">Pin shows the pins your screensaver has downloaded. Hidden pins never appear in the screensaver and aren't downloaded again.
      Pin reads Pinterest's public RSS feeds, or your home feed when you connect your session cookie. Nothing leaves this computer except requests to Pinterest.</div>
      <div class="foot"><button class="link" data-m="page">Release notes on GitHub</button></div>`,
      async (m, el) => {
        if (m === 'close') closeModal();
        else if (m === 'toggle') {
          const k = el.dataset.key;
          settings = await api.set_setting(k, !settings[k]);
          el.querySelector('.switch').classList.toggle('on', !!settings[k]);
        } else if (m === 'check') { upd = await api.check_updates(); renderUpdateRow(); renderPill(); }
        else if (m === 'see-update') openUpdate();
        else if (m === 'page') api.open_url(upd ? upd.page : 'https://github.com/YuvrajxGarg/pin/releases');
        else if (m === 'savedir') { settings = await api.choose_save_dir(); renderSavePath(); openSettings(); }
        else if (m === 'saver-settings') api.open_saver_settings();
      }, 'settings');
    renderUpdateRow();
  }
  function renderPill() {
    const p = $('#update-pill');
    if (!upd || !['available', 'downloading', 'ready', 'installing'].includes(upd.phase)) { p.classList.add('hidden'); return; }
    p.classList.remove('hidden');
    p.innerHTML = upd.phase === 'ready' ? `${icon('refresh')}Restart to update` :
      upd.phase === 'downloading' ? `${icon('download')}Updating ${Math.round(upd.progress * 100)}%` :
      upd.phase === 'installing' ? `${icon('refresh')}Installing…` : `${icon('download')}Update to ${esc(upd.latest)}`;
  }
  function patchUpdateProgress() {
    const bar = $('#modal-root .progress > div');
    const line = $('#modal-root .update-hero p');
    if (!bar || !line) return false;
    const pct = Math.round((upd.progress || 0) * 100);
    bar.style.width = pct + '%';
    line.textContent = `Downloading… ${pct}%`;
    return true;
  }
  function openUpdate() {
    if (!upd) return;
    const ph = upd.phase;
    const pct = Math.round((upd.progress || 0) * 100);
    const sub = ph === 'ready' ? 'Downloaded and ready. Restart now, or it installs the next time you quit.' :
      ph === 'downloading' ? `Downloading… ${pct}%` : ph === 'installing' ? 'Installing and restarting…' :
      ph === 'failed' ? (upd.error || 'Something went wrong.') : ph === 'uptodate' ? "You're on the newest version." :
      `You have ${esc(upd.current)}.` + (upd.can_install ? '' : ' This copy runs from source, so the download page opens instead.');
    const primary = ph === 'ready' ? `<button class="btn-primary inline" data-m="install">${icon('refresh')}Restart to update</button>` :
      ph === 'available' || ph === 'failed' ? `<button class="btn-primary inline" data-m="${upd.can_install ? 'download' : 'page'}">${icon('download')}${upd.can_install ? 'Download update' : 'Open download page'}</button>` : '';
    showModal('update', `
      <div class="update-hero">
        <div class="logomark lg">${MARK(30)}</div>
        <div><h2>${upd.latest ? 'Pin ' + esc(upd.latest) : 'Updates'}</h2><p class="${ph === 'failed' ? 'err' : ''}">${sub}</p></div>
      </div>
      ${ph === 'downloading' ? `<div class="progress"><div style="width:${pct}%"></div></div>` : ''}
      ${upd.notes ? `<div class="label">What's new</div><div class="notes">${esc(upd.notes)}</div>` : ''}
      <div class="foot"><button class="link" data-m="page">View on GitHub</button><button class="btn-quiet" data-m="close">Later</button>${primary}</div>`,
      (m) => {
        if (m === 'close') closeModal();
        else if (m === 'install') api.install_update();
        else if (m === 'download') api.download_update();
        else if (m === 'page') api.open_url(upd.page);
      });
  }

  // ---------- events from Python ----------
  window.App = {
    on(event, p) {
      if (event === 'update') {
        const prev = upd && upd.phase;
        upd = p; renderPill();
        if (modal === 'update' && p.phase === 'downloading' && prev === 'downloading' && patchUpdateProgress()) return;
        if (modal === 'update') openUpdate();
        if (modal === 'settings') renderUpdateRow();
      } else if (event === 'busy') {
        busy = p.busy; renderBusy();
      } else if (event === 'new_pins') {
        const now = Date.now() / 1000;
        for (const id of p.ids) {
          if (!pins.find((x) => x.id === id)) { pins.unshift({ id, t: now, hidden: false }); fresh.add(id); }
        }
        setTimeout(() => p.ids.forEach((id) => fresh.delete(id)), 2600);
        loadThumbs();
      } else if (event === 'refreshed') {
        busy = false; renderBusy();
        if (p.error === 'access') load();
        else if (p.error) toast(p.error, true);
        else toast(p.new ? `${p.new} new pin${p.new === 1 ? '' : 's'}` : 'No new pins right now. Pinterest sends a fresh batch every few minutes.', !p.new && false);
        load();
      }
    },
  };

  // ---------- wiring ----------
  $('#cols').addEventListener('click', (e) => {
    const t = e.target.closest('.tile');
    if (!t) return;
    const id = t.dataset.id;
    const a = e.target.closest('[data-a]');
    const p = pins.find((x) => x.id === id);
    if (!p) return;
    if (a) {
      if (a.dataset.a === 'save') save([id]);
      else if (a.dataset.a === 'hide') setHidden([id], !p.hidden);
      else if (a.dataset.a === 'open') openViewer(id);
      return;
    }
    if (e.target.closest('.check') || e.metaKey || e.ctrlKey || e.shiftKey || sel.size) toggleSel(id);
    else openViewer(id);
  });
  $('#view-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b || b.dataset.v === view) return;
    view = b.dataset.v;
    document.querySelectorAll('#view-tabs button').forEach((x) => x.classList.toggle('on', x === b));
    clearSel();
    $('#grid').scrollTop = 0;
    layout();
  });
  $('#refresh-btn').onclick = () => refresh(false);
  $('#start-over').onclick = () => refresh(true);
  $('#change-source').onclick = openSource;
  $('#open-settings').onclick = openSettings;
  $('#open-saved').onclick = () => api.open_save_dir();
  $('#save-row').onclick = async () => { settings = await api.choose_save_dir(); renderSavePath(); };
  $('#select-all').onclick = () => { visible().forEach((p) => sel.add(p.id)); layout(); };
  $('#save-all').onclick = () => save(visible().map((p) => p.id));
  $('#sel-save').onclick = () => save([...sel]);
  $('#sel-hide').onclick = () => setHidden([...sel], view !== 'hidden');
  $('#sel-clear').onclick = clearSel;
  $('#saver-install').onclick = async () => {
    const s = saverSt || {};
    if (s.installed && s.current) { api.open_saver_settings(); return; }
    const r = await api.install_saver();
    saverSt = r.saver; renderSaver();
    toast(r.text, !r.ok);
  };
  $('#saver-preview').onclick = () => {
    if (!(saverSt && saverSt.installed)) { toast('Install the screensaver first', true); return; }
    api.start_saver();
  };
  $('#speed').oninput = (e) => { $('#speed-val').textContent = e.target.value + ' pt/s'; setCfg('speed', +e.target.value, 250); };
  $('#tile').oninput = (e) => { $('#tile-val').textContent = e.target.value + ' pt'; setCfg('tile', +e.target.value, 250); };
  $('#opt-clock').onclick = () => { cfg.clock = !cfg.clock; renderSource(); setCfg('clock', cfg.clock); };
  $('#opt-24h').onclick = () => { if (!cfg.clock) return; cfg.clock24h = !cfg.clock24h; renderSource(); setCfg('clock24h', cfg.clock24h); };
  $('#update-pill').onclick = () => openUpdate();

  // ---------- start ----------
  async function start(a) {
    api = a;
    const info = await api.info();
    platform = info.platform;
    document.body.classList.add(platform === 'darwin' ? 'mac' : platform.startsWith('win') ? 'win' : 'other');
    $('#version').textContent = 'v' + info.version;
    settings = info.settings || {};
    home = info.home || '';
    upd = info.update;
    renderSavePath();
    renderPill();
    await load();
    if (location.search.includes('splash')) return; // ?demo&splash keeps the intro up for previews
    setTimeout(() => { $('#splash').classList.add('out'); $('#app').classList.add('in'); layout(); }, 1950);
    setTimeout(() => $('#splash').remove(), 2550);
    if (access && !pins.length) setTimeout(() => refresh(false), 2150);
  }

  // Demo data for previewing the UI in a plain browser (open index.html?demo).
  function demoApi() {
    const pal = [['#3a2f5c', '#c06c84'], ['#1f3b4d', '#5fb3b3'], ['#4a3b1f', '#e0a458'], ['#2b3a2b', '#8fbf6a'], ['#3d1f2b', '#e05a6b'], ['#232946', '#b8c1ec'], ['#1b262c', '#3282b8'], ['#2d2424', '#e0c097']];
    const ratio = [1.5, 1.25, 1.78, 1, 1.33, 2.1, .75, 1.6, 1.4, 1.2];
    const mk = (i) => {
      const [a, b] = pal[i % pal.length]; const r = ratio[i % ratio.length]; const h = Math.round(300 * r);
      return { src: 'data:image/svg+xml;utf8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="300" height="${h}"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="300" height="${h}" fill="url(#g)"/><circle cx="${80 + (i * 37) % 160}" cy="${h * .4}" r="${40 + (i % 4) * 12}" fill="rgba(255,255,255,.22)"/><rect x="30" y="${h * .7}" width="${120 + (i % 3) * 40}" height="10" rx="5" fill="rgba(255,255,255,.3)"/></svg>`), ratio: r, w: 736, h: Math.round(736 * r) };
    };
    let all = Array.from({ length: 34 }, (_, i) => ({ id: 'p' + i + '.img', t: 1000 - i, hidden: i % 11 === 5 }));
    let dcfg = { feed: 'nasa', home: true, source: 'Your home feed', speed: 26, clock: true, clock24h: false, tile: 300, hiddenCount: 3 };
    return {
      info: async () => ({ version: '1.0.0', platform: location.search.includes('win') ? 'win32' : 'darwin', home: '/Users/demo',
        settings: { auto_check: true, auto_install: true, save_dir: '/Users/demo/Pictures/Pin' },
        update: { phase: location.search.includes('update') ? 'ready' : 'uptodate', current: '1.0.0', latest: '1.1.0', progress: 0, can_install: true, notes: '- Faster refresh', page: 'https://github.com', last_checked: new Date().toISOString() } }),
      state: async () => (location.search.includes('denied') ? { access: false, saver: {} } : { access: true, config: dcfg, pins: all.slice(), saver: { installed: '1.0.0', bundled: '1.0.0', current: true }, busy: false }),
      thumbs: async (ids) => Object.fromEntries(ids.map((id) => [id, mk(+id.slice(1, -4))])),
      full: async (id) => mk(+id.slice(1, -4)),
      set_hidden: async (ids, h) => { all.forEach((p) => { if (ids.includes(p.id)) p.hidden = h; }); return { ok: true, hiddenCount: all.filter((p) => p.hidden).length }; },
      save_pins: async (ids) => ({ saved: ids.length, dir: '/Users/demo/Pictures/Pin', last: '/Users/demo/Pictures/Pin/x.jpg' }),
      refresh: async () => { App.on('busy', { busy: true }); setTimeout(() => { const n = all.length; const ids = [0, 1, 2].map((k) => 'p' + (n + k) + '.img'); ids.forEach((id) => all.unshift({ id, t: 2000, hidden: false })); App.on('new_pins', { ids }); App.on('refreshed', { new: 3 }); App.on('busy', { busy: false }); }, 1200); return true; },
      set_config: async (k, v) => { dcfg = Object.assign({}, dcfg, { [k]: v }); return dcfg; },
      set_cookie: async (v) => { dcfg = Object.assign({}, dcfg, { home: !!v, source: v ? 'Your home feed' : dcfg.feed }); return dcfg; },
      set_setting: async (k, v) => { settings[k] = v; return Object.assign({}, settings); },
      choose_save_dir: async () => settings, check_updates: async () => upd, download_update() {}, install_update() {}, open_url() {},
      copy_pin: async () => true, reveal_saved() {}, open_save_dir() {}, install_saver: async () => ({ ok: true, text: 'Screensaver installed.', saver: { installed: '1.0.0', bundled: '1.0.0', current: true } }),
      start_saver() {}, open_saver_settings() {}, open_privacy() {}, check_access: async () => true,
    };
  }

  if (!location.search.includes('demo')) {
    let started = false;
    const reveal = (msg) => {
      const s = $('#splash');
      if (!s || s.classList.contains('out')) return;
      s.classList.add('out'); $('#app').classList.add('in');
      if (msg) toast(msg, true);
    };
    const boot = () => {
      const a = window.pywebview && window.pywebview.api;
      if (started || !a || typeof a.info !== 'function') return;
      started = true;
      start(a).catch((e) => reveal("Pin couldn't start: " + ((e && e.message) || e)));
    };
    window.addEventListener('pywebviewready', boot);
    boot();
    setTimeout(() => reveal(started ? '' : "Pin's engine didn't answer. Quit Pin and open it again."), 15000);
  } else {
    start(demoApi());
  }
})();
