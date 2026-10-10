(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const SVGNS = 'http://www.w3.org/2000/svg';
  const API = () => window.SFA_API;

  /* Each dashboard section is fetched, cached and refreshed independently. */
  const SECTIONS = {
    profile: 'getFarm', irrigation: 'getIrrigation', financials: 'getFinancials', fertilizers: 'getFertilizers',
    inspections: 'getInspections', weather: 'getForecast'
  };
  const state = {
    lang: 'en', view: 'overview', busy: false,
    farms: [], farmsErr: false, farmsOrigin: null, farmId: null,
    sec: {}, tok: {},
    recs: { status: 'idle', data: null }, recTok: 0
  };
  Object.keys(SECTIONS).forEach((k) => { state.sec[k] = { status: 'loading', data: null }; state.tok[k] = 0; });

  const t = (k, vars) => {
    let s = (window.SFA_I18N[state.lang][k] != null ? window.SFA_I18N[state.lang][k] : window.SFA_I18N.en[k]) || k;
    if (vars) Object.keys(vars).forEach((v) => { s = s.replace('{' + v + '}', vars[v]); });
    return s;
  };
  const tOpt = (k) => { const d = window.SFA_I18N[state.lang]; return d[k] != null ? d[k] : null; };
  const loc = () => (state.lang === 'ar' ? 'ar-JO-u-nu-latn' : 'en-GB');
  const fmtNum = (n) => new Intl.NumberFormat(loc(), { maximumFractionDigits: 2 }).format(n);
  const jod = (n) => t('jod', { n: fmtNum(n) });
  const data = (name) => (state.sec[name].status === 'ok' ? state.sec[name].data : null);
  function fmtDate(s) {
    if (!s) return null;
    const d = /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(s + 'T12:00:00') : new Date(s);
    return isNaN(d) ? String(s) : new Intl.DateTimeFormat(loc(), { day: 'numeric', month: 'short', year: 'numeric' }).format(d);
  }
  const pickText = (v) => (v && typeof v === 'object' ? v[state.lang] || v.en || '' : String(v || ''));

  /* ---------- toast ---------- */
  let toastTimer;
  function toast(msg) {
    const n = $('#toast'); n.textContent = msg; n.classList.add('on');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => n.classList.remove('on'), 2800);
  }

  /* ---------- language ---------- */
  function applyLang(l, animate) {
    const run = () => {
      state.lang = l;
      const h = document.documentElement; h.lang = l; h.dir = l === 'ar' ? 'rtl' : 'ltr';
      document.title = t('pageTitle');
      $$('[data-i18n]').forEach((e) => { e.textContent = t(e.dataset.i18n); });
      $$('[data-i18n-aria]').forEach((e) => e.setAttribute('aria-label', t(e.dataset.i18nAria)));
      $$('[data-i18n-ph]').forEach((e) => e.setAttribute('placeholder', t(e.dataset.i18nPh)));
      $$('[data-set-lang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.setLang === l)));
      $('#dlg-src').textContent = API().isLive() ? t('dataSrcLive') : t('dataSrcSample');
      $('#art .plant').alt = t('cropVal');
      renderAll();
      $$('.msg[data-i18n-msg]').forEach((m) => { m.querySelector('.who').textContent = t(m.dataset.i18nMsg); });
      $$('.msg .demo-tag').forEach((m) => { m.textContent = t('demoLabel'); });
      $$('.msg .src-h').forEach((m) => { m.textContent = t('sources'); });
      try { localStorage.setItem('sfa-lang', l); } catch (e) {}
      const re = $('#report-err'); if (re) { re.hidden = true; re.textContent = ''; }
    };
    if (!animate || matchMedia('(prefers-reduced-motion: reduce)').matches) return run();
    const app = $('#app'); app.classList.add('swap');
    setTimeout(() => { run(); app.classList.remove('swap'); }, 200);
  }

  /* ---------- views ---------- */
  const FOCUS_TARGET = { overview: '#card-ai', irrigation: '#m-irr', weather: '#card-weather', analytics: '#card-crop', cropHealth: '.stage', farm: '#profile', fertilizer: '#fert-panel', financial: '#m-cost' };
  function applyFocus() {
    const v = state.view;
    $$('[data-focus]').forEach((n) => {
      const f = n.dataset.focus.split(' ');
      n.classList.toggle('dim', v !== 'overview' && !f.includes(v));
      n.classList.toggle('focus', v !== 'overview' && f.includes(v) && n.matches('.card,.metric,.ai,.profile'));
    });
  }
  function setView(v) {
    state.view = v;
    $('#app').dataset.view = v;
    $$('.tab').forEach((b) => { const on = b.dataset.view === v; b.classList.toggle('active', on); b.setAttribute('aria-current', on ? 'page' : 'false'); });
    $$('.sbtn[data-view]').forEach((b) => { const on = b.dataset.view === v; b.classList.toggle('active', on); b.setAttribute('aria-current', on ? 'page' : 'false'); });
    applyFocus();
    if (matchMedia('(max-width: 860px)').matches) {
      const tg = $(FOCUS_TARGET[v]); if (tg) tg.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  /* ---------- helpers ---------- */
  function icon(id, size, cls) {
    const s = document.createElementNS(SVGNS, 'svg'); s.setAttribute('width', size); s.setAttribute('height', size);
    if (cls) s.setAttribute('class', cls);
    const u = document.createElementNS(SVGNS, 'use'); u.setAttribute('href', '#' + id); s.appendChild(u); return s;
  }
  function retryBtn(section) {
    const r = el('button', 'retry', t('retry')); r.type = 'button'; r.addEventListener('click', () => loadSection(section)); return r;
  }
  function stateBox(msg, section) {
    const b = el('div', 'state'); b.appendChild(el('p', null, msg));
    if (section) b.appendChild(retryBtn(section));
    return b;
  }
  const anySample = (names) => names.some((n) => data(n) && data(n).origin === 'sample');

  /* ---------- profile ---------- */
  function enumLabel(prefix, v) { return tOpt(prefix + '_' + String(v).toLowerCase()) || String(v); }
  function renderProfile() {
    const sel = $('#farm-select'); sel.replaceChildren();
    if (state.farmsErr) { sel.appendChild(new Option(t('loadErr'), '')); sel.disabled = true; }
    else if (!state.farms.length) { sel.appendChild(new Option(t('profileNone'), '')); sel.disabled = true; }
    else {
      state.farms.forEach((f) => {
        const o = new Option(f.name || '–', f.id); if (f.label) o.title = f.label;
        o.selected = f.id === state.farmId; sel.appendChild(o);
      });
      sel.disabled = false;
    }
    const dl = $('#p-items'); dl.replaceChildren();
    const s = state.sec.profile, p = data('profile');
    const chip = $('#p-chip'); chip.hidden = !(p && p.origin === 'sample'); chip.textContent = t('sample');
    if (s.status === 'error' || state.farmsErr) { dl.appendChild(stateBox(t('loadErr'), state.farmsErr ? null : 'profile')); dl.firstChild.classList.add('inline'); return; }
    const items = [
      ['pLocation', p && p.location],
      ['pArea', p && p.area_dunum != null ? t('area', { n: fmtNum(p.area_dunum) }) : null],
      ['pPlanted', p && fmtDate(p.planting_date)],
      ['pStage', p && p.crop_stage ? enumLabel('stage', p.crop_stage) : null],
      ['pMethod', p && p.irrigation_method ? enumLabel('method', p.irrigation_method) : null]
    ];
    items.forEach(([k, v]) => {
      const d = el('div', 'p-item'); d.appendChild(el('dt', null, t(k)));
      if (s.status === 'loading') d.appendChild(el('dd', 'skel'));
      else d.appendChild(el('dd', v ? null : 'na', v || t('na')));
      dl.appendChild(d);
    });
  }
  function renderStageNote() {
    const p = data('profile'), n = $('#note-stage');
    n.className = (p && p.crop_stage) ? '' : 'muted';
    n.textContent = p && p.crop_stage ? enumLabel('stage', p.crop_stage) : (state.sec.profile.status === 'loading' ? '…' : t('na'));
  }

  /* ---------- weather ---------- */
  const WX_ICON = { sunny: 'i-sun', partly: 'i-partly', cloudy: 'i-cloud', rain: 'i-rain', unknown: 'i-cloud' };
  const WX_NAME = { sunny: 'sunny', partly: 'partly', cloudy: 'cloudy', rain: 'rainy', unknown: 'wxUnknown' };
  function renderWeather() {
    const body = $('#wx-body'), chip = $('#wx-chip'), foot = $('#wx-foot'), s = state.sec.weather;
    body.replaceChildren(); foot.textContent = ''; chip.hidden = true;
    if (s.status === 'loading') { for (let i = 0; i < 7; i++) body.appendChild(el('div', 'skel')); return; }
    if (s.status === 'error') { body.appendChild(stateBox(t('wxEmpty'), 'weather')); return; }
    const f = s.data;
    if (!f || !f.days.length) {
      const msg = f && f.missing_inputs && f.missing_inputs.length ? t('wxNoCoordinates') :
        f && f.weather_status === 'unavailable' ? t('wxUnavailable') : t('wxEmpty');
      body.appendChild(stateBox(msg, 'weather'));
      const retry = el('button', 'retry', t('retry')); retry.type = 'button'; retry.addEventListener('click', () => loadSection('weather'));
      body.lastChild.appendChild(retry); return;
    }
    const base = f.date ? new Date(f.date + 'T12:00:00') : null;
    if (f.origin === 'sample') { chip.hidden = false; chip.textContent = t('sample'); }
    if (base) {
      const stamp = f.fetched_at ? new Date(f.fetched_at) : base;
      const d = new Intl.DateTimeFormat(loc(), { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Amman', ...(f.fetched_at ? { hour: '2-digit', minute: '2-digit' } : {}) }).format(stamp);
      const source = f.source || (state.lang === 'ar' ? 'مصدر الطقس' : 'Weather source');
      const dateLabel = f.weather_status === 'cached' ? 'wxCached' : f.fetched_at ? 'wxSourceUpdated' : f.origin === 'sample' ? 'wxSampleDate' : 'wxLive';
      foot.textContent = t(dateLabel, { d, s: source });
    }
    const hi = f.days.map((d) => d.high).filter((n) => typeof n === 'number');
    const max = Math.max(...hi, 1), min = Math.min(...hi, 0);
    f.days.forEach((day, i) => {
      const row = el('div', 'wx-row');
      const dt = day.date ? new Date(day.date + 'T12:00:00') : base ? new Date(base.getTime() + i * 864e5) : null;
      row.appendChild(el('span', 'wd', dt ? new Intl.DateTimeFormat(loc(), { weekday: 'short' }).format(dt) : '–'));
      const ic = icon(WX_ICON[day.condition] || 'i-cloud', 22, 'wi'); ic.setAttribute('role', 'img');
      ic.setAttribute('aria-label', t(WX_NAME[day.condition] || 'cloudy')); row.appendChild(ic);
      const bar = el('span', 'bar'); const fill = el('i');
      const pct = typeof day.high === 'number' ? 18 + ((day.high - min) / Math.max(max - min, 1)) * 72 : 0;
      fill.style.setProperty('--w', pct + '%'); bar.appendChild(fill); row.appendChild(bar);
      row.appendChild(el('span', 'wr', typeof day.rain_mm === 'number' ? fmtNum(day.rain_mm) + ' ' + t('mm') : t('na')));
      const tmp = (typeof day.high === 'number' ? fmtNum(day.high) + '°' : '–') + ' / ' + (typeof day.low === 'number' ? fmtNum(day.low) + '°' : '–');
      const tt = el('span', 'wt', tmp); tt.dir = 'ltr'; row.appendChild(tt);
      body.appendChild(row);
    });
  }

  /* ---------- crop overview (data-completeness check, no calculations) ---------- */
  const LEVEL = { available: 0.9, review: 0.55, missing: 0.22 };
  function computeCrop() {
    const p = data('profile'), ir = data('irrigation'), fin = data('financials'), wx = data('weather');
    const confirmed = ir ? ir.records.filter((r) => r && r.confirmed === true).length : 0;
    return [
      { key: 'growth', status: p && p.crop_stage ? 'available' : 'missing' },
      { key: 'water', status: ir && ir.estimate && ir.estimate.value != null ? 'available' : confirmed ? 'review' : 'missing' },
      { key: 'nutrient', status: fin && fin.fertilizer_budget_jod != null ? 'available' : 'missing' },
      { key: 'weather', status: wx && wx.days.length ? (wx.weather_status === 'live' && wx.days.length === 7 ? 'available' : 'review') : 'missing' },
      { key: 'activity', status: confirmed && fin && fin.recorded_costs_jod != null ? 'available' : (confirmed || (fin && fin.recorded_costs_jod != null)) ? 'review' : 'missing' }
    ];
  }
  function renderRadar() {
    const host = $('#radar'); host.replaceChildren();
    const chip = $('#crop-chip'); chip.hidden = !anySample(Object.keys(SECTIONS)); chip.textContent = t('sample');
    if (Object.keys(SECTIONS).every((k) => state.sec[k].status === 'loading')) { for (let i = 0; i < 4; i++) host.appendChild(el('div', 'skel')); return; }
    const ind = computeCrop(), n = ind.length, cx = 150, cy = 112, R = 72;
    const svg = document.createElementNS(SVGNS, 'svg'); svg.setAttribute('viewBox', '35 10 230 210'); svg.setAttribute('class', 'radar');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', t('cropTitle') + ': ' + ind.map((i) => t('g_' + i.key) + ' – ' + t(i.status)).join(', '));
    const pt = (i, r) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / n; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; };
    const mk = (tag, attrs) => { const e = document.createElementNS(SVGNS, tag); Object.keys(attrs).forEach((k) => e.setAttribute(k, attrs[k])); svg.appendChild(e); return e; };
    [0.25, 0.5, 0.75, 1].forEach((k) => mk('polygon', { points: ind.map((_, i) => pt(i, R * k).join(',')).join(' '), class: 'grid' }));
    ind.forEach((_, i) => { const p = pt(i, R); mk('line', { x1: cx, y1: cy, x2: p[0], y2: p[1], class: 'grid' }); });
    mk('polygon', { points: ind.map((d, i) => pt(i, R * LEVEL[d.status]).join(',')).join(' '), class: 'shape' });
    ind.forEach((d, i) => { const p = pt(i, R * LEVEL[d.status]); mk('circle', { cx: p[0], cy: p[1], r: 2.6, class: 'pt ' + d.status }); });
    ind.forEach((d, i) => {
      const p = pt(i, R + 17), a = p[0] < cx - 6 ? 'end' : p[0] > cx + 6 ? 'start' : 'middle';
      const name = mk('text', { x: p[0], y: p[1] - (i === 0 ? 4 : 0), 'text-anchor': a, class: 'lbl' }); name.textContent = t('g_' + d.key);
      const st = mk('text', { x: p[0], y: p[1] + 11 - (i === 0 ? 4 : 0), 'text-anchor': a, class: 'lbl-s ' + d.status }); st.textContent = t(d.status);
    });
    host.appendChild(svg);
  }

  /* ---------- summary metrics ---------- */
  function metric(id, ico, label, value, subs, focus, na) {
    const m = el('div', 'metric'); m.id = id; m.dataset.focus = focus;
    const c = el('span', 'mi'); c.appendChild(icon(ico, 18)); m.appendChild(c);
    const tx = el('div', 'mt');
    tx.appendChild(el('small', null, label));
    const v = el('b', na ? 'na' : null); if (typeof value === 'string') v.textContent = value; else v.appendChild(value);
    tx.appendChild(v);
    (subs || []).forEach((s) => { if (s == null) return; if (typeof s === 'string') tx.appendChild(el('span', null, s)); else if (s.nodeType) tx.appendChild(s); else tx.appendChild(el('span', s.cls || null, s.text)); });
    m.appendChild(tx); return m;
  }
  /* Builds a metric whose data section may be loading / failed / present. */
  function slot(section, id, ico, label, focus, build) {
    const s = state.sec[section];
    if (s.status === 'loading') { const m = el('div', 'metric'); m.id = id; m.dataset.focus = focus; m.appendChild(el('div', 'skel tall')); m.firstChild.style.flex = '1'; return m; }
    if (s.status === 'error') return metric(id, ico, label, t('loadErr'), [retryBtn(section)], focus, true);
    return build(s.data);
  }
  function projLine(v) { return v != null ? { text: t('projected', { v: jod(v) }), cls: 'proj' } : { text: t('projNA'), cls: 'proj' }; }

  function renderMetrics() {
    const g = $('#sum-grid'); g.replaceChildren();
    const NA = t('na'), F = (s) => 'overview ' + s;
    g.appendChild(slot('profile', 'm-farm', 'i-map', t('farmPlot'), F('farm analytics'), (p) => {
      if (!p) return metric('m-farm', 'i-map', t('farmPlot'), NA, [t('areaNA')], F('farm analytics'), true);
      return metric('m-farm', 'i-map', t('farmPlot'), p.name || NA, [p.area_dunum != null ? t('area', { n: fmtNum(p.area_dunum) }) : t('areaNA')], F('farm analytics'), !p.name);
    }));
    g.appendChild(slot('irrigation', 'm-irr', 'i-drop', t('irrig'), F('irrigation analytics'), (ir) => {
      const last = (ir ? ir.records : []).filter((r) => r && r.confirmed === true && r.date).sort((a, b) => String(b.date).localeCompare(String(a.date)))[0];
      const dt = last ? fmtDate(last.date) : null;
      const hasEstimate = ir && ir.estimate && ir.estimate.value != null;
      const est = hasEstimate ? { text: t('irrEst', { v: '\u2066' + fmtNum(ir.estimate.value) + (ir.estimate.unit ? ' ' + ir.estimate.unit : '') + '\u2069' }), cls: 'proj' } : { text: t('irrNoEst'), cls: 'proj' };
      const missing = ir && ir.estimate && ir.estimate.missing_inputs || [];
      let reason = null;
      if (missing.includes('supported_drip_method')) reason = t('irrMethodUnsupported');
      else if (missing.includes('latitude') || missing.includes('longitude') || missing.includes('usable_weather_forecast')) reason = t('irrNeedWeather');
      else if (missing.length) reason = t('irrNeedInputs');
      return metric('m-irr', 'i-drop', t('irrig'), dt || t('irrNone'), [dt ? t('irrLatest') : null, est, reason], F('irrigation analytics'), !dt);
    }));
    g.appendChild(slot('financials', 'm-cost', 'i-coins', t('costs'), F('financial analytics'), (f) => {
      const v = f && f.recorded_costs_jod;
      return metric('m-cost', 'i-coins', t('costs'), v != null ? jod(v) : NA, [t('recSub'), projLine(f && f.projected_costs_jod)], F('financial analytics'), v == null);
    }));
    g.appendChild(slot('financials', 'm-rev', 'i-chart', t('revenue'), F('financial analytics'), (f) => {
      const v = f && f.actual_revenue_jod;
      return metric('m-rev', 'i-chart', t('revenue'), v != null ? jod(v) : NA, [t('revSub'), projLine(f && f.projected_revenue_jod)], F('financial analytics'), v == null);
    }));
    g.appendChild(slot('financials', 'm-fert', 'i-flask', t('fertBudget'), F('fertilizer analytics'), (f) => {
      const v = f && f.fertilizer_budget_jod;
      return metric('m-fert', 'i-flask', t('fertBudget'), v != null ? jod(v) : NA, [v != null ? t('fertSub') : t('fertNA')], F('fertilizer analytics'), v == null);
    }));
    g.appendChild(slot('inspections', 'm-alert', 'i-bolt', t('alerts'), F('cropHealth analytics'), (d) => {
      const list = d ? d.reminders : null;
      let val = NA;
      if (list) { val = el('span'); val.appendChild(document.createTextNode(fmtNum(list.length) + ' ')); val.appendChild(el('em', null, t('alertsVal'))); }
      const next = list && list[0] ? { text: t('nextRem', { t: pickText(list[0].title) }), cls: 'proj' } : null;
      return metric('m-alert', 'i-bolt', t('alerts'), val, [t('alertsSub'), next], F('cropHealth analytics'), !list);
    }));
    const chip = $('#sum-chip'); chip.hidden = !anySample(['profile', 'irrigation', 'financials', 'inspections']); chip.textContent = t('sample');
    const ins = data('inspections'); $('#notif-dot').hidden = !(ins && ins.reminders.length > 0);
    applyFocus();
  }

  /* ---------- recommendations (rendered by the shared SFA_REC component) ---------- */
  function renderRecs() {
    if (window.SFA_VOICE) window.SFA_VOICE.destroyPlayers();
    const r = state.recs, cnt = $('#recs-count');
    const n = r.status === 'ok' ? r.data.recommendations.length : null;
    cnt.hidden = n == null; cnt.textContent = n == null ? '' : fmtNum(n);
    const farm = state.farms.find((f) => f.id === state.farmId);
    $('#recs-for').textContent = farm && farm.name ? t('recsFor', { n: farm.name }) : '';
    const note = $('#recs-note'); note.hidden = r.status !== 'ok';
    if (r.status === 'ok') note.textContent = r.data.origin === 'api' ? t('recsApiNote') : t('recsDemoNote');
    note.className = 'recs-note ' + (r.status === 'ok' && r.data.origin !== 'api' ? 'demo' : '');
    const body = $('#recs-body'); body.replaceChildren();
    if (r.status === 'loading' || r.status === 'idle') { for (let i = 0; i < 3; i++) body.appendChild(el('div', 'skel tall')); return; }
    if (r.status === 'error') { const b = stateBox(t('recErr')); const rb = el('button', 'retry', t('retry')); rb.type = 'button'; rb.addEventListener('click', () => loadRecs()); b.appendChild(rb); body.appendChild(b); return; }
    if (!r.data.recommendations.length) { body.appendChild(stateBox(t('recEmpty'))); return; }
    r.data.recommendations.forEach((rec) => body.appendChild(window.SFA_REC.render(rec, state.lang, { voice: { lang: state.lang, farmId: state.farmId } })));
  }
  async function loadRecs(quiet) {
    const my = ++state.recTok, farm = state.farmId;
    if (!farm) { state.recs = { status: 'ok', data: { origin: 'api', recommendations: [] } }; renderRecs(); return; }
    if (!quiet || state.recs.status !== 'ok') state.recs = { status: 'loading', data: null };
    renderRecs();
    try {
      const d = await API().getRecommendations(farm);
      if (my !== state.recTok || farm !== state.farmId) return;
      state.recs = { status: 'ok', data: d };
    } catch (e) {
      if (my !== state.recTok || farm !== state.farmId) return;
      state.recs = { status: 'error', data: null };
    }
    renderRecs();
  }

  function renderFertilizers() {
    const body = $('#fert-body'), chip = $('#fert-chip'), s = state.sec.fertilizers;
    body.replaceChildren(); chip.hidden = true;
    if (s.status === 'loading') { body.appendChild(el('div', 'skel tall')); return; }
    if (s.status === 'error') {
      const box = stateBox(t('fertLoadError'));
      const retry = el('button', 'retry', t('retry')); retry.type = 'button'; retry.addEventListener('click', () => loadSection('fertilizers'));
      box.appendChild(retry); body.appendChild(box); return;
    }
    const catalog = s.data;
    if (!catalog || !catalog.products.length) { body.appendChild(el('p', 'fert-state', t('fertUnavailable'))); return; }
    chip.hidden = catalog.origin !== 'supplier_snapshot'; chip.textContent = t('fertRetailSnapshot');
    const date = catalog.updated_at ? fmtDate(catalog.updated_at) : t('na');
    body.appendChild(el('p', 'fert-meta', t('fertSourceDate', { source: catalog.source || t('na'), date })));
    body.appendChild(el('p', 'fert-note', catalog.budget_jod == null ? t('fertNoBudget') : t('fertBudgetLabel', { value: jod(catalog.budget_jod) })));
    catalog.products.forEach((p) => {
      const card = el('article', 'fert-product');
      card.appendChild(el('h3', null, state.lang === 'ar' ? (p.name_ar || p.name) : p.name));
      card.appendChild(el('p', 'fert-profile', (state.lang === 'ar' ? p.profile_ar : p.profile) || t('na')));
      const packageUnit = state.lang === 'ar' && p.package_unit === 'kg' ? 'كغم' : p.package_unit;
      card.appendChild(el('div', 'fert-price', t('fertPackagePrice', { price: p.price_jod == null ? t('na') : jod(p.price_jod), pack: p.package_quantity == null ? t('na') : fmtNum(p.package_quantity) + ' ' + (packageUnit || '') })));
      card.appendChild(el('div', 'fert-price', t('fertUnitPrice', { price: p.price_per_kg_jod == null ? t('na') : jod(p.price_per_kg_jod) })));
      card.appendChild(el('p', 'fert-fit', (state.lang === 'ar' ? p.source_fit_ar : p.source_fit) || t('na')));
      let comparison;
      if (p.within_budget_for_one_pack === true) comparison = t('fertOnePackFits', { value: jod(p.budget_remaining_after_one_pack_jod) });
      else if (p.within_budget_for_one_pack === false) comparison = t('fertOnePackOver', { value: jod(Math.abs(p.budget_remaining_after_one_pack_jod)) });
      else comparison = t('fertNoBudget');
      card.appendChild(el('p', 'fert-note', t('fertBudgetCompare', { result: comparison })));
      const a = el('a', 'fert-source', t('fertViewSource')); a.href = p.source_url; a.target = '_blank'; a.rel = 'noopener noreferrer'; card.appendChild(a);
      body.appendChild(card);
    });
    body.appendChild(el('p', 'fert-note', state.lang === 'ar' ? catalog.notice_ar : catalog.notice));
  }
  function renderAll() { renderProfile(); renderStageNote(); renderMetrics(); renderWeather(); renderRadar(); renderRecs(); renderFertilizers(); }
  function renderSection(name) {
    if (name === 'weather') renderWeather();
    else if (name === 'fertilizers') renderFertilizers();
    else { if (name === 'profile') { renderProfile(); renderStageNote(); } renderMetrics(); }
    renderRadar();
  }

  /* ---------- data loading ---------- */
  async function loadSection(name, quiet) {
    const my = ++state.tok[name], farm = state.farmId, s = state.sec[name];
    if (!farm) { s.status = 'ok'; s.data = null; renderSection(name); return; }
    if (!quiet || s.status !== 'ok') s.status = 'loading';
    renderSection(name);
    try {
      const d = await API()[SECTIONS[name]](farm);
      if (my !== state.tok[name] || farm !== state.farmId) return; // stale
      s.status = 'ok'; s.data = d;
    } catch (e) {
      if (my !== state.tok[name] || farm !== state.farmId) return;
      s.status = 'error'; s.data = null;
    }
    renderSection(name);
  }
  function loadAll(quiet) { return Promise.allSettled(Object.keys(SECTIONS).map((n) => loadSection(n, quiet))); }

  async function loadFarms() {
    try {
      const r = await API().getFarms();
      state.farms = r.farms; state.farmsOrigin = r.origin; state.farmsErr = false;
      let saved = null; try { saved = localStorage.getItem('sfa-farm'); } catch (e) {}
      state.farmId = state.farms.some((f) => f.id === saved) ? saved : (state.farms[0] ? state.farms[0].id : null);
    } catch (e) { state.farmsErr = true; state.farms = []; state.farmId = null; }
    renderProfile();
  }
  function selectFarm(id) {
    state.farmId = id || null; try { localStorage.setItem('sfa-farm', id); } catch (e) {}
    Object.keys(SECTIONS).forEach((k) => { state.sec[k] = { status: 'loading', data: null }; });
    state.recs = { status: 'loading', data: null };
    renderAll(); loadAll().then(() => loadRecs());
  }

  /* Refresh only the sections affected by a successful API write. */
  window.addEventListener('sfa:data-updated', (e) => {
    const d = e.detail || {};
    if (d.farmId && d.farmId !== state.farmId) return;
    (d.sections && d.sections.length ? d.sections : Object.keys(SECTIONS)).forEach((n) => { if (SECTIONS[n]) loadSection(n, true); });
    loadRecs(true); // recommendations depend on every section
  });

  /* ---------- chat ---------- */
  function addMsg(role, text, opts) {
    opts = opts || {};
    const box = $('#msgs'), m = el('div', 'msg ' + role + (opts.error ? ' err' : ''));
    m.dataset.i18nMsg = role === 'user' ? 'you' : 'assistant';
    m.appendChild(el('span', 'who', t(m.dataset.i18nMsg)));
    const body = el('p', 'txt'); body.textContent = text; m.appendChild(body);
    if (opts.demo) m.appendChild(el('span', 'demo-tag', t('demoLabel')));
    if (opts.fallback) m.appendChild(el('span', 'demo-tag', state.lang === 'ar' ? 'إجابة احتياطية موثقة — دون توليد بالذكاء الاصطناعي' : 'Sourced fallback — no AI generation'));
    if (opts.sources && opts.sources.length) {
      const s = el('div', 'srcs'); s.appendChild(el('span', 'src-h', t('sources')));
      const ul = el('ul');
      opts.sources.forEach((x) => {
        const li = el('li'); const title = String((x && (x.title || x.url)) || '');
        if (x && /^https?:\/\//i.test(x.url || '')) { const a = el('a', null, title); a.href = x.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; li.appendChild(a); }
        else li.textContent = title;
        ul.appendChild(li);
      });
      s.appendChild(ul); m.appendChild(s);
    }
    box.appendChild(m); $('#card-ai').classList.add('has-msgs'); box.scrollTop = box.scrollHeight; return m;
  }
  function typing() {
    const m = el('div', 'msg bot typing'); m.setAttribute('aria-label', t('thinking'));
    m.appendChild(el('span', 'who', t('assistant')));
    const d = el('span', 'dots'); d.setAttribute('role', 'status'); d.append(el('i'), el('i'), el('i')); m.appendChild(d);
    $('#msgs').appendChild(m); $('#msgs').scrollTop = 1e6; return m;
  }
  async function send(e) {
    e.preventDefault();
    const inp = $('#chat-input'), text = inp.value.trim();
    if (!text || state.busy) return;
    state.busy = true; inp.value = ''; $('#chat-send').disabled = true;
    addMsg('user', text);
    const tp = typing();
    try {
      const r = await API().askAssistant(text, state.lang, state.farmId);
      tp.remove();
      if (!r.answer) throw new Error('empty');
      addMsg('bot', r.answer, { demo: r.origin === 'demo', fallback: r.origin === 'fallback', sources: r.sources });
    } catch (err) {
      tp.remove(); addMsg('bot', t('aiError'), { error: true });
    }
    state.busy = false; $('#chat-send').disabled = false; inp.focus();
  }

  /* ---------- PDF report (frozen snapshot of the selected farm) ---------- */
  function cloneJson(v) { try { return v == null ? v : JSON.parse(JSON.stringify(v)); } catch (e) { return null; } }
  function getReportSnapshot() {
    const farm = state.farms.find((f) => f.id === state.farmId);
    return {
      generatedAt: new Date().toISOString(),
      lang: state.lang,
      live: API().isLive(),
      farmId: state.farmId,
      farmName: farm && farm.name ? farm.name : null,
      farmLabel: farm && farm.label ? farm.label : null,
      farmsOrigin: state.farmsOrigin,
      sections: {
        profile: cloneJson(state.sec.profile),
        irrigation: cloneJson(state.sec.irrigation),
        financials: cloneJson(state.sec.financials),
        inspections: cloneJson(state.sec.inspections),
        weather: cloneJson(state.sec.weather)
      },
      recs: cloneJson(state.recs)
    };
  }
  async function generateReport() {
    const errEl = $('#report-err'), btn = $('#btn-report'), label = btn.querySelector('[data-i18n]');
    errEl.hidden = true; errEl.textContent = '';
    if (!state.farmId) {
      errEl.hidden = false; errEl.textContent = t('pdfErr_NO_FARM'); toast(t('pdfErr_NO_FARM')); return;
    }
    btn.disabled = true;
    if (label) label.textContent = t('reportBusy');
    const snap = getReportSnapshot();
    try {
      if (!window.SFA_REPORT) throw Object.assign(new Error('NO_LIB'), { code: 'NO_LIB' });
      await window.SFA_REPORT.download(snap);
      toast(t('reportOk'));
    } catch (e) {
      const key = 'pdfErr_' + ((e && e.code) || 'GEN_FAIL');
      const msg = tOpt(key) || t('pdfErr_GEN_FAIL');
      errEl.hidden = false; errEl.textContent = msg; toast(msg);
    }
    btn.disabled = false;
    if (label) label.textContent = t('reportBtn');
  }

  /* ---------- init ---------- */
  async function init() {
    let l = 'en';
    try { const s = localStorage.getItem('sfa-lang'); if (s === 'ar' || s === 'en') l = s; } catch (e) {}
    const q = new URLSearchParams(location.search).get('lang'); if (q === 'ar' || q === 'en') l = q;
    applyLang(l, false);
    setView('overview');

    $('#lang-btn').addEventListener('click', () => applyLang(state.lang === 'en' ? 'ar' : 'en', true));
    $$('[data-view]').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
    $('#btn-search').addEventListener('click', () => $('#chat-input').focus());
    $('#btn-notif').addEventListener('click', () => {
      const ins = data('inspections');
      toast(ins ? t('toastNotif', { n: fmtNum(ins.reminders.length) }) : t('toastNotifNA')); setView('cropHealth');
    });
    $('#btn-refresh').addEventListener('click', async () => {
      const b = $('#btn-refresh'); b.classList.add('spin'); b.disabled = true;
      if (state.farmsErr || !state.farms.length) { await loadFarms(); }
      await loadAll(true); await loadRecs(true); b.classList.remove('spin'); b.disabled = false; toast(t('toastRefreshed'));
    });
    $('#farm-select').addEventListener('change', (e) => selectFarm(e.target.value));
    $('#btn-report').addEventListener('click', generateReport);
    $('#thumb-add').addEventListener('click', () => toast(t('toastAdd')));
    $$('.thumb:not(.add)').forEach((b) => b.addEventListener('click', () => {
      $$('.thumb:not(.add)').forEach((x) => { x.classList.toggle('selected', x === b); x.setAttribute('aria-pressed', String(x === b)); });
    }));
    $('#s-settings').addEventListener('click', () => $('#dlg-settings').showModal());
    $('#btn-recs').addEventListener('click', () => $('#dlg-recs').showModal());
    $('#s-help').addEventListener('click', () => $('#dlg-help').showModal());
    $$('[data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));
    $$('dialog').forEach((d) => d.addEventListener('click', (e) => { if (e.target === d) d.close(); }));
    $$('[data-set-lang]').forEach((b) => b.addEventListener('click', () => applyLang(b.dataset.setLang, true)));
    $('#chat-form').addEventListener('submit', send);

    await loadFarms();
    loadAll().then(() => loadRecs());
  }
  init();
})();
