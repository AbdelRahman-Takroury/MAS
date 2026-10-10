/* Farm PDF report. Built from a frozen dashboard snapshot so numbers
 * match the on-screen farm and SFA_REC.resolve() output. No values are invented. */
(function () {
  'use strict';

  const FONT = 'Amiri';
  const FONT_REG = 'assets/fonts/Amiri-Regular.ttf';
  const FONT_BOLD = 'assets/fonts/Amiri-Bold.ttf';
  const INK = [10, 17, 10], MUTED = [90, 100, 88], LINE = [210, 216, 200];
  const BAND = [22, 38, 26], LIME = [90, 138, 32], AMBER = [138, 106, 16], WHITE = [255, 255, 255];
  let fontCache = null;
  const pdfVisual = (value) => {
    const text = String(value == null ? '' : value).replace(/[\u2066-\u2069\u200e\u200f]/g, '');
    return /[\u0600-\u06ff]/.test(text) ? window.SFA_ARABIC.toVisual(text) : text;
  };

  const fail = (code, cause) => { const e = new Error(code); e.code = code; e.cause = cause; return e; };
  const clone = (v) => { try { return v == null ? v : JSON.parse(JSON.stringify(v)); } catch (e) { return null; } };
  const num = (v) => (typeof v === 'number' && isFinite(v) ? v : null);
  const str = (v) => (typeof v === 'string' && v.trim() ? v.trim() : null);

  function tr(lang, k, vars) {
    const d = window.SFA_I18N || {};
    let s = (d[lang] && d[lang][k] != null) ? d[lang][k] : (d.en && d.en[k] != null ? d.en[k] : k);
    if (vars) Object.keys(vars).forEach((v) => { s = String(s).replace('{' + v + '}', vars[v]); });
    return s;
  }
  const loc = (lang) => (lang === 'ar' ? 'ar-JO-u-nu-latn' : 'en-GB');
  const nf = (lang, n, digits = 2) => new Intl.NumberFormat(loc(lang), { maximumFractionDigits: digits }).format(n);
  const jod = (lang, n) => tr(lang, 'jod', { n: nf(lang, n, 3) });
  const perKg = (lang, n) => nf(lang, n, 4) + (lang === 'ar' ? ' دينار/كغم' : ' JOD/kg');
  function fmtDate(lang, s) {
    if (!s) return null;
    const d = /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(s + 'T12:00:00') : new Date(s);
    return isNaN(d) ? String(s) : new Intl.DateTimeFormat(loc(lang), { day: 'numeric', month: 'short', year: 'numeric' }).format(d);
  }
  function fmtDateTime(lang, iso) {
    const d = new Date(iso);
    if (isNaN(d)) return String(iso || '');
    return new Intl.DateTimeFormat(loc(lang), { dateStyle: 'medium', timeStyle: 'short' }).format(d);
  }
  const pick = (v, lang) => {
    if (window.SFA_REC) return window.SFA_REC.pick(v, lang).text;
    if (v && typeof v === 'object') return v[lang] || v.en || '';
    return v == null ? '' : String(v);
  };
  const na = (lang) => tr(lang, 'na');
  const money = (lang, v) => (v == null ? na(lang) : jod(lang, v));
  const enumLabel = (lang, prefix, v) => {
    if (!v) return na(lang);
    const k = prefix + '_' + String(v).toLowerCase();
    const d = window.SFA_I18N[lang];
    return (d && d[k] != null) ? d[k] : String(v);
  };

  function b64(buf) {
    const bytes = new Uint8Array(buf);
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }
  async function loadFonts() {
    if (fontCache) return fontCache;
    const url = (p) => new URL(p, document.baseURI).href;
    let reg, bold;
    try {
      const [a, b] = await Promise.all([fetch(url(FONT_REG)), fetch(url(FONT_BOLD))]);
      if (!a.ok || !b.ok) throw fail('NO_FONT');
      reg = await a.arrayBuffer();
      bold = await b.arrayBuffer();
    } catch (e) { throw e.code ? e : fail('NO_FONT', e); }
    if (!reg.byteLength || !bold.byteLength) throw fail('NO_FONT');
    fontCache = { reg: b64(reg), bold: b64(bold) };
    return fontCache;
  }

  function originOf(sec) { return sec && sec.status === 'ok' && sec.data ? sec.data.origin : null; }
  function snapshotHasSimulated(snap) {
    const o = [];
    Object.keys(snap.sections || {}).forEach((k) => { const x = originOf(snap.sections[k]); if (x && x !== 'api') o.push(x); });
    if (snap.recs && snap.recs.status === 'ok' && snap.recs.data && snap.recs.data.origin && snap.recs.data.origin !== 'api') o.push(snap.recs.data.origin);
    if (snap.farmsOrigin && snap.farmsOrigin !== 'api') o.push(snap.farmsOrigin);
    return o;
  }

  function derivedFinance(fin) {
    if (!fin) return {};
    const harvest = num(fin.expected_harvest_kg);
    const actualHarvest = num(fin.actual_harvest_kg);
    const activeSeasonHarvest = num(fin.actual_harvest_active_season_kg);
    const pc = num(fin.projected_costs_jod), pr = num(fin.projected_revenue_jod);
    const rc = num(fin.recorded_costs_jod), ar = num(fin.actual_revenue_jod);
    const opts = Array.isArray(fin.fertilizer_options) ? fin.fertilizer_options.filter((x) => x && (x.name || x.title)) : [];
    return {
      expected_harvest_kg: harvest,
      actual_harvest_kg: actualHarvest,
      actual_harvest_active_season_kg: activeSeasonHarvest,
      projected_profit_jod: fin.server_calculated ? num(fin.projected_profit_jod) : (pr != null && pc != null) ? pr - pc : null,
      actual_profit_jod: fin.server_calculated ? num(fin.actual_profit_jod) : (ar != null && rc != null) ? ar - rc : null,
      cost_per_kg_jod: fin.server_calculated ? num(fin.cost_per_kg_jod) : (harvest != null && harvest > 0 && pc != null) ? pc / harvest : null,
      cost_per_kg_recorded_jod: fin.server_calculated ? num(fin.cost_per_kg_recorded_jod) : (actualHarvest != null && actualHarvest > 0 && rc != null) ? rc / actualHarvest : null,
      break_even_price_jod: fin.server_calculated ? num(fin.break_even_price_jod) : (harvest != null && harvest > 0 && pc != null) ? pc / harvest : null,
      fertilizer_options: opts,
      fert_share: (num(fin.fertilizer_budget_jod) != null && rc != null && rc !== 0) ? (fin.fertilizer_budget_jod / rc) * 100 : null
    };
  }

  function missingList(snap, lang) {
    const items = [];
    const add = (s) => items.push(s);
    const sec = snap.sections || {};
    Object.keys(sec).forEach((k) => {
      const s = sec[k];
      if (!s) return;
      if (s.status === 'error') add(tr(lang, 'pdfMissErr', { s: tr(lang, 'pdfSec_' + k) }));
      else if (s.status === 'loading') add(tr(lang, 'pdfMissLoad', { s: tr(lang, 'pdfSec_' + k) }));
    });
    if (snap.recs && snap.recs.status === 'error') add(tr(lang, 'pdfMissErr', { s: tr(lang, 'pdfSec_recs') }));
    if (snap.recs && snap.recs.status === 'loading') add(tr(lang, 'pdfMissLoad', { s: tr(lang, 'pdfSec_recs') }));
    const p = sec.profile && sec.profile.status === 'ok' ? sec.profile.data : null;
    if (p) {
      if (!p.location) add(tr(lang, 'pLocation'));
      if (p.area_dunum == null) add(tr(lang, 'pArea'));
      if (!p.planting_date) add(tr(lang, 'pPlanted'));
      if (!p.crop_stage) add(tr(lang, 'pStage'));
      if (!p.irrigation_method) add(tr(lang, 'pMethod'));
    }
    const ir = sec.irrigation && sec.irrigation.status === 'ok' ? sec.irrigation.data : null;
    if (ir && !ir.estimate) add(tr(lang, 'pdfIrrEst'));
    const fin = sec.financials && sec.financials.status === 'ok' ? sec.financials.data : null;
    const d = derivedFinance(fin);
    if (fin) {
      if (fin.projected_costs_jod == null) add(tr(lang, 'pdfProjCosts'));
      if (fin.projected_revenue_jod == null) add(tr(lang, 'pdfProjRev'));
      if (fin.fertilizer_budget_jod == null) add(tr(lang, 'fertBudget'));
      if (fin.actual_revenue_jod == null) add(tr(lang, 'revenue'));
      if (!d.fertilizer_options.length) add(tr(lang, 'pdfFertOpts'));
      if (d.expected_harvest_kg == null) add(tr(lang, 'pdfHarvest'));
    }
    const wx = sec.weather && sec.weather.status === 'ok' ? sec.weather.data : null;
    if (wx && (!wx.days || !wx.days.length)) add(tr(lang, 'pdfWxDays'));
    return items;
  }

  function assumptions(snap, lang) {
    const a = [tr(lang, 'pdfAsmSnap')];
    if (snapshotHasSimulated(snap).length) a.push(tr(lang, 'pdfAsmSample'));
    a.push(tr(lang, 'pdfAsmIrr'));
    a.push(tr(lang, 'pdfAsmProj'));
    a.push(tr(lang, 'pdfAsmDerived'));
    a.push(tr(lang, 'pdfAsmNoInvent'));
    const recs = snap.recs && snap.recs.status === 'ok' ? snap.recs.data : null;
    if (recs && recs.origin === 'demo') a.push(tr(lang, 'pdfAsmDemoRec'));
    return a;
  }

  /* ---------- drawing ---------- */
  function layout(doc, rtl) {
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const mL = 50, mR = 50, mT = 86, mB = 48;
    const x0 = mL, x1 = pageW - mR, width = x1 - x0;
    let y = mT;
    const visual = pdfVisual;
    const measure = (t) => doc.getTextWidth(visual(t));

    function setF(bold, size, color) {
      doc.setFont(FONT, bold ? 'bold' : 'normal');
      doc.setFontSize(size);
      if (color) doc.setTextColor(color[0], color[1], color[2]);
    }
    function wrap(text, maxW, bold, size) {
      setF(bold, size);
      const raw = String(text == null ? '' : text);
      if (!raw) return [''];
      const words = raw.split(/\s+/);
      const lines = [];
      let cur = '';
      const push = (s) => { if (s) lines.push(s); };
      words.forEach((w) => {
        const trial = cur ? cur + ' ' + w : w;
        if (measure(trial) <= maxW) { cur = trial; return; }
        push(cur); cur = '';
        if (measure(w) <= maxW) { cur = w; return; }
        let chunk = '';
        Array.from(w).forEach((ch) => {
          if (measure(chunk + ch) <= maxW) chunk += ch;
          else { push(chunk); chunk = ch; }
        });
        cur = chunk;
      });
      push(cur);
      return lines.length ? lines : [''];
    }
    function ensure(h) {
      if (y + h <= pageH - mB) return;
      doc.addPage();
      y = mT;
    }
    function textLine(text, opts) {
      opts = opts || {};
      const size = opts.size || 10.5;
      const bold = !!opts.bold;
      const color = opts.color || INK;
      const gap = opts.lh || size + 4;
      const indent = opts.indent || 0;
      const maxW = width - indent;
      const lines = wrap(text, maxW, bold, size);
      lines.forEach((ln) => {
        ensure(gap);
        setF(bold, size, color);
        const vis = visual(ln);
        if (rtl) doc.text(vis, x1 - indent, y, { align: 'right' });
        else doc.text(vis, x0 + indent, y);
        y += gap;
      });
    }
    function pair(label, value) {
      ensure(16);
      setF(false, 9, MUTED);
      const lab = visual(label);
      const lw = doc.getTextWidth(lab);
      if (rtl) doc.text(lab, x1, y, { align: 'right' });
      else doc.text(lab, x0, y);
      setF(false, 10.5, INK);
      const val = String(value == null || value === '' ? na(rtl ? 'ar' : 'en') : value);
      const vLines = wrap(val, width - Math.max(lw + 16, 130), false, 10.5);
      vLines.forEach((ln, i) => {
        if (i) ensure(14);
        setF(false, 10.5, INK);
        const vis = visual(ln);
        if (rtl) doc.text(vis, x0, y);
        else doc.text(vis, x1, y, { align: 'right' });
        y += 14;
      });
    }
    function rule() {
      ensure(10);
      doc.setDrawColor(LINE[0], LINE[1], LINE[2]);
      doc.setLineWidth(0.6);
      doc.line(x0, y, x1, y);
      y += 12;
    }
    function h2(title) {
      ensure(36);
      y += 6;
      setF(true, 13, BAND);
      const vis = visual(title);
      if (rtl) doc.text(vis, x1, y, { align: 'right' });
      else doc.text(vis, x0, y);
      y += 6;
      doc.setDrawColor(LIME[0], LIME[1], LIME[2]);
      doc.setLineWidth(1.4);
      doc.line(x0, y, x1, y);
      y += 14;
    }
    function bullet(text) {
      const mark = rtl ? '•' : '•';
      const lines = wrap(text, width - 14, false, 10.5);
      lines.forEach((ln, i) => {
        ensure(14);
        setF(false, 10.5, INK);
        if (i === 0) {
          if (rtl) { doc.text(visual(mark), x1, y, { align: 'right' }); doc.text(visual(ln), x1 - 12, y, { align: 'right' }); }
          else { doc.text(mark, x0, y); doc.text(visual(ln), x0 + 12, y); }
        } else {
          if (rtl) doc.text(visual(ln), x1 - 12, y, { align: 'right' });
          else doc.text(visual(ln), x0 + 12, y);
        }
        y += 14;
      });
    }
    function chip(text, amber) {
      const pad = 6;
      setF(true, 8, amber ? WHITE : BAND);
      const vis = visual(text);
      const w = doc.getTextWidth(vis) + pad * 2;
      const h = 14;
      ensure(h + 4);
      const cx = rtl ? x1 - w : x0;
      doc.setFillColor.apply(doc, amber ? AMBER : [232, 236, 214]);
      doc.roundedRect(cx, y - 10, w, h, 3, 3, 'F');
      if (rtl) doc.text(vis, cx + w - pad, y, { align: 'right' });
      else doc.text(vis, cx + pad, y);
      y += 16;
    }

    return { pageW, pageH, x0, x1, width, mT, mB, rtl, getY: () => y, setY: (v) => { y = v; }, ensure, textLine, pair, rule, h2, bullet, chip, setF, visual };
  }

  function paintChrome(doc, snap, lang, rtl, page, pages) {
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const x0 = 50, x1 = pageW - 50;
    doc.setFillColor(BAND[0], BAND[1], BAND[2]);
    doc.rect(0, 0, pageW, 70, 'F');
    doc.setFillColor(LIME[0], LIME[1], LIME[2]);
    doc.rect(0, 70, pageW, 3, 'F');
    doc.setFont(FONT, 'bold');
    doc.setFontSize(16);
    doc.setTextColor(255, 255, 255);
    const brand = pdfVisual(tr(lang, 'pdfTitle'));
    if (rtl) doc.text(brand, x1, 24, { align: 'right' });
    else doc.text(brand, x0, 24);
    doc.setFont(FONT, 'normal');
    doc.setFontSize(9);
    doc.setTextColor(210, 220, 200);
    const farmLine = snap.farmName || na(lang);
    const meta = fmtDateTime(lang, snap.generatedAt) + ' · ' + (lang === 'ar' ? tr(lang, 'pdfLangAr') : tr(lang, 'pdfLangEn'));
    let headerFarm = farmLine;
    while (headerFarm.length > 1 && doc.getTextWidth(pdfVisual(headerFarm)) > x1 - x0) headerFarm = headerFarm.slice(0, -2) + '…';
    const visFarm = pdfVisual(headerFarm);
    const visMeta = pdfVisual(meta);
    if (rtl) { doc.text(visFarm, x1, 42, { align: 'right' }); doc.text(visMeta, x1, 56, { align: 'right' }); }
    else { doc.text(visFarm, x0, 42); doc.text(visMeta, x0, 56); }
    doc.setDrawColor(LINE[0], LINE[1], LINE[2]);
    doc.setLineWidth(0.5);
    doc.line(x0, pageH - 32, x1, pageH - 32);
    doc.setFont(FONT, 'normal');
    doc.setFontSize(8);
    doc.setTextColor(MUTED[0], MUTED[1], MUTED[2]);
    const footL = pdfVisual(tr(lang, 'pdfFooter'));
    const footR = pdfVisual(tr(lang, 'pdfPage', { n: String(page), t: String(pages) }));
    if (rtl) {
      doc.text(footL, x1, pageH - 18, { align: 'right' });
      doc.text(footR, x0, pageH - 18);
    } else {
      doc.text(footL, x0, pageH - 18);
      doc.text(footR, x1, pageH - 18, { align: 'right' });
    }
  }

  function wxName(lang, c) {
    const map = { sunny: 'sunny', partly: 'partly', cloudy: 'cloudy', rain: 'rainy' };
    return tr(lang, map[c] || 'cloudy');
  }

  function fillBody(L, snap, lang) {
    const sec = snap.sections || {};
    const val = (section, ok) => {
      const s = sec[section];
      if (!s) return { kind: 'na', text: na(lang) };
      if (s.status === 'loading') return { kind: 'load', text: tr(lang, 'pdfStillLoading') };
      if (s.status === 'error') return { kind: 'err', text: tr(lang, 'loadErr') };
      return ok(s.data);
    };
    const sim = snapshotHasSimulated(snap);

    L.textLine(tr(lang, 'pdfIntro'), { size: 10.5, color: MUTED, lh: 15 });
    if (sim.length) L.chip(tr(lang, 'pdfDemoChip'), true);
    else L.chip(tr(lang, 'pdfLiveChip'), false);
    L.textLine(tr(lang, snap.live ? 'dataSrcLive' : 'dataSrcSample'), { size: 9.5, color: MUTED, lh: 13 });
    L.rule();

    /* 2. Farm profile */
    L.h2(tr(lang, 'pdfH_profile'));
    const prof = val('profile', (p) => {
      if (!p) return { kind: 'na', text: na(lang), data: null };
      return { kind: 'ok', data: p };
    });
    if (prof.kind !== 'ok' || !prof.data) L.textLine(prof.text || na(lang), { color: MUTED });
    else {
      const p = prof.data;
      if (p.origin && p.origin !== 'api') L.chip(tr(lang, 'sample'), true);
      L.pair(tr(lang, 'farmSelect'), p.name || snap.farmName || na(lang));
      L.pair(tr(lang, 'crop'), tr(lang, 'cropVal'));
      L.pair(tr(lang, 'pLocation'), p.location || na(lang));
      L.pair(tr(lang, 'pArea'), p.area_dunum != null ? tr(lang, 'area', { n: nf(lang, p.area_dunum) }) : na(lang));
      L.pair(tr(lang, 'pPlanted'), fmtDate(lang, p.planting_date) || na(lang));
      L.pair(tr(lang, 'pStage'), p.crop_stage ? enumLabel(lang, 'stage', p.crop_stage) : na(lang));
      L.pair(tr(lang, 'pMethod'), p.irrigation_method ? enumLabel(lang, 'method', p.irrigation_method) : na(lang));
      L.pair(tr(lang, 'cond'), tr(lang, 'condVal'));
      L.pair(tr(lang, 'leaf'), tr(lang, 'leafVal'));
    }

    /* 3. Weather */
    L.h2(tr(lang, 'pdfH_weather'));
    const wx = val('weather', (f) => ({ kind: f && f.days && f.days.length ? 'ok' : 'empty', data: f }));
    if (wx.kind === 'load' || wx.kind === 'err') L.textLine(wx.text, { color: MUTED });
    else if (wx.kind === 'empty' || !wx.data || !wx.data.days || !wx.data.days.length) L.textLine(tr(lang, 'wxEmpty'), { color: MUTED });
    else {
      const f = wx.data;
      if (f.origin === 'sample') L.chip(tr(lang, 'sample'), true);
      const src = str(f.source) || (f.origin === 'sample' ? tr(lang, 'pdfWxSrcSample') : tr(lang, 'pdfWxSrcApi'));
      L.pair(tr(lang, 'pdfWxSource'), src);
      L.pair(tr(lang, 'pdfWxTime'), fmtDate(lang, f.fetched_at || f.date) || na(lang));
      f.days.forEach((day, i) => {
        const dt = day.date ? fmtDate(lang, day.date) : (f.date ? fmtDate(lang, f.date) : null);
        const hi = typeof day.high === 'number' ? nf(lang, day.high) + '°' : na(lang);
        const lo = typeof day.low === 'number' ? nf(lang, day.low) + '°' : na(lang);
        const rain = typeof day.rain_mm === 'number' ? nf(lang, day.rain_mm) + ' ' + tr(lang, 'mm') : na(lang);
        L.bullet((dt || ('#' + (i + 1))) + ' — ' + wxName(lang, day.condition) + ' · ' + hi + ' / ' + lo + ' · ' + tr(lang, 'rain') + ' ' + rain);
      });
    }

    /* 4. Irrigation */
    L.h2(tr(lang, 'pdfH_irr'));
    const irv = val('irrigation', (ir) => ({ kind: 'ok', data: ir }));
    if (irv.kind !== 'ok') L.textLine(irv.text, { color: MUTED });
    else if (!irv.data) L.textLine(na(lang), { color: MUTED });
    else {
      const ir = irv.data;
      if (ir.origin === 'sample') L.chip(tr(lang, 'sample'), true);
      const recs = (ir.records || []).filter((r) => r && r.confirmed === true && r.date)
        .sort((a, b) => String(b.date).localeCompare(String(a.date)));
      const unconf = (ir.records || []).filter((r) => r && r.confirmed !== true).length;
      L.pair(tr(lang, 'pdfIrrCount'), recs.length ? nf(lang, recs.length) : na(lang));
      if (!recs.length) L.textLine(tr(lang, 'irrNone'), { color: MUTED });
      else recs.forEach((r) => L.bullet(fmtDate(lang, r.date)));
      if (unconf) L.textLine(tr(lang, 'pdfIrrUnconf', { n: nf(lang, unconf) }), { size: 9.5, color: MUTED });
      if (ir.estimate && num(ir.estimate.value) != null) {
        L.pair(tr(lang, 'pdfIrrEst'), '\u2066' + nf(lang, ir.estimate.value) + (ir.estimate.unit ? ' ' + ir.estimate.unit : '') + '\u2069');
        L.textLine(tr(lang, 'pdfIrrEstNote'), { size: 9.5, color: MUTED, lh: 13 });
        const basis = lang === 'ar' ? ir.estimate.basis_ar : ir.estimate.basis;
        if (basis) L.textLine(basis, { size: 9.5, color: MUTED, lh: 13 });
        const estimateWarnings = lang === 'ar' ? ir.estimate.warnings_ar : ir.estimate.warnings;
        (estimateWarnings || []).forEach((warning) => L.textLine(warning, { size: 9.5, color: MUTED, lh: 13 }));
      } else L.pair(tr(lang, 'pdfIrrEst'), tr(lang, 'irrNoEst'));
    }

    /* 5. Inspections */
    L.h2(tr(lang, 'pdfH_insp'));
    const inv = val('inspections', (d) => ({ kind: 'ok', data: d }));
    if (inv.kind !== 'ok') L.textLine(inv.text, { color: MUTED });
    else if (!inv.data) L.textLine(na(lang), { color: MUTED });
    else {
      const d = inv.data;
      if (d.origin === 'sample') L.chip(tr(lang, 'sample'), true);
      L.textLine(tr(lang, 'alertsSub'), { size: 9.5, color: MUTED, lh: 13 });
      const list = d.reminders || [];
      if (!list.length) L.textLine(tr(lang, 'pdfInspNone'), { color: MUTED });
      list.forEach((r, i) => {
        L.textLine((i + 1) + '. ' + (pick(r.title, lang) || na(lang)), { bold: true, size: 11 });
        L.pair(tr(lang, 'pdfInspDue'), fmtDate(lang, r.due_date) || na(lang));
        L.pair(tr(lang, 'pdfInspWhy'), pick(r.reason, lang) || na(lang));
      });
      const recs = snap.recs && snap.recs.status === 'ok' && snap.recs.data ? snap.recs.data.recommendations : [];
      const inspRec = (recs || []).find((r) => r && r.topic === 'inspection');
      if (inspRec && window.SFA_REC) {
        const resolved = window.SFA_REC.resolve(inspRec, lang);
        L.textLine(tr(lang, 'pdfInspFromRec'), { size: 9.5, color: MUTED, lh: 13 });
        L.textLine(resolved.why.text, { size: 10.5, lh: 14 });
      }
    }

    /* 6. Fertilizer */
    L.h2(tr(lang, 'pdfH_fert'));
    const fv = val('financials', (f) => ({ kind: 'ok', data: f }));
    if (fv.kind !== 'ok') L.textLine(fv.text, { color: MUTED });
    else if (!fv.data) L.textLine(na(lang), { color: MUTED });
    else {
      const f = fv.data;
      const der = derivedFinance(f);
      if (f.origin === 'sample') L.chip(tr(lang, 'sample'), true);
      L.pair(tr(lang, 'fertBudget'), money(lang, f.fertilizer_budget_jod));
      L.pair(tr(lang, 'costs'), money(lang, f.recorded_costs_jod));
      if (der.fert_share != null) L.pair(tr(lang, 'pdfFertShare'), nf(lang, der.fert_share) + '%');
      else L.pair(tr(lang, 'pdfFertShare'), na(lang));
      L.textLine(tr(lang, 'pdfFertShareNote'), { size: 9, color: MUTED, lh: 13 });
      L.textLine(tr(lang, 'pdfFertOpts'), { bold: true, size: 11 });
      if (der.fertilizer_options.length) {
        der.fertilizer_options.forEach((o) => {
          const name = pick(o.name || o.title, lang) || na(lang);
          const cost = num(o.cost_jod) != null ? jod(lang, o.cost_jod) : na(lang);
          L.bullet(name + ' — ' + cost);
        });
      } else L.textLine(na(lang), { color: MUTED });
      L.textLine(tr(lang, 'pdfNoDose'), { size: 9.5, color: MUTED, lh: 13 });
    }

    /* 7. Costs */
    L.h2(tr(lang, 'pdfH_costs'));
    if (fv.kind !== 'ok') L.textLine(fv.text, { color: MUTED });
    else if (!fv.data) L.textLine(na(lang), { color: MUTED });
    else {
      L.pair(tr(lang, 'costs'), money(lang, fv.data.recorded_costs_jod));
      L.pair(tr(lang, 'pdfProjCosts'), money(lang, fv.data.projected_costs_jod));
      L.textLine(tr(lang, 'pdfCostsNote'), { size: 9.5, color: MUTED, lh: 13 });
    }

    /* 8. Harvest */
    L.h2(tr(lang, 'pdfH_harvest'));
    if (fv.kind !== 'ok') L.textLine(fv.text, { color: MUTED });
    else if (!fv.data) L.textLine(na(lang), { color: MUTED });
    else {
      const der = derivedFinance(fv.data);
      L.pair(tr(lang, 'pdfHarvest'), der.expected_harvest_kg != null ? nf(lang, der.expected_harvest_kg) + ' ' + tr(lang, 'pdfKg') : na(lang));
      if (!fv.data.server_calculated) L.pair(tr(lang, 'pdfHarvestAct'), der.actual_harvest_kg != null ? nf(lang, der.actual_harvest_kg) + ' ' + tr(lang, 'pdfKg') : na(lang));
      L.pair(tr(lang, 'pdfHarvestActive'), der.actual_harvest_active_season_kg != null ? nf(lang, der.actual_harvest_active_season_kg) + ' ' + tr(lang, 'pdfKg') : na(lang));
      L.pair(tr(lang, 'pdfCostKg'), der.cost_per_kg_jod != null ? perKg(lang, der.cost_per_kg_jod) : na(lang));
      L.textLine(tr(lang, 'pdfCostKgNote'), { size: 9, color: MUTED, lh: 13 });
    }

    /* 9. Revenue / profit / break-even */
    L.h2(tr(lang, 'pdfH_rev'));
    if (fv.kind !== 'ok') L.textLine(fv.text, { color: MUTED });
    else if (!fv.data) L.textLine(na(lang), { color: MUTED });
    else {
      const der = derivedFinance(fv.data);
      L.pair(tr(lang, 'revenue'), money(lang, fv.data.actual_revenue_jod));
      L.pair(tr(lang, 'pdfProjRev'), money(lang, fv.data.projected_revenue_jod));
      L.pair(tr(lang, 'pdfProjProfit'), money(lang, der.projected_profit_jod));
      L.pair(tr(lang, 'pdfActProfit'), money(lang, der.actual_profit_jod));
      L.pair(tr(lang, 'pdfBreakEven'), der.break_even_price_jod != null ? perKg(lang, der.break_even_price_jod) : na(lang));
      L.textLine(tr(lang, 'pdfRevNote'), { size: 9, color: MUTED, lh: 13 });
    }

    /* 10. Recommendations */
    L.h2(tr(lang, 'pdfH_recs'));
    const rs = snap.recs;
    if (!rs || rs.status === 'loading') L.textLine(tr(lang, 'pdfStillLoading'), { color: MUTED });
    else if (rs.status === 'error') L.textLine(tr(lang, 'recErr'), { color: MUTED });
    else if (!rs.data || !rs.data.recommendations || !rs.data.recommendations.length) L.textLine(tr(lang, 'recEmpty'), { color: MUTED });
    else {
      L.textLine(rs.data.origin === 'api' ? tr(lang, 'recsApiNote') : tr(lang, 'recsDemoNote'), { size: 9.5, color: MUTED, lh: 13 });
      rs.data.recommendations.forEach((rec, idx) => {
        const r = window.SFA_REC.resolve(rec, lang);
        L.ensure(52);
        L.textLine((idx + 1) + '. ' + r.topicLabel, { bold: true, size: 12, color: BAND });
        L.chip(r.origin === 'api' ? tr(lang, 'recFromApi') : r.origin === 'demo' ? tr(lang, 'recDemo') : tr(lang, 'sample'), r.origin !== 'api');
        L.textLine(tr(lang, 'recSituation'), { bold: true, size: 9.5, color: MUTED, lh: 12 });
        L.textLine(r.summary.text, { size: 10.5, lh: 14 });
        L.textLine(tr(lang, 'recAction'), { bold: true, size: 9.5, color: MUTED, lh: 12 });
        L.textLine(r.action.text, { size: 10.5, lh: 14 });
        L.textLine(tr(lang, 'recWhy'), { bold: true, size: 9.5, color: MUTED, lh: 12 });
        L.textLine(r.why.text, { size: 10.5, lh: 14 });
        L.textLine(tr(lang, 'recLimits'), { bold: true, size: 9.5, color: MUTED, lh: 12 });
        if (r.limitations.length) r.limitations.forEach((x) => L.bullet(x.text));
        else L.textLine('–', { color: MUTED });
        L.textLine(tr(lang, 'recSources'), { bold: true, size: 9.5, color: MUTED, lh: 12 });
        if (r.sources.length) r.sources.forEach((s) => L.bullet(s.title.text + (s.url ? ' — ' + s.url : '')));
        else L.textLine(tr(lang, 'recNoSources'), { color: MUTED });
        if (r.evidence.length) {
          L.textLine(tr(lang, 'recBasis'), { bold: true, size: 9.5, color: MUTED, lh: 12 });
          r.evidence.forEach((e) => L.pair(e.label, e.value));
        }
        L.rule();
      });
    }

    /* 11. Missing + disclaimer */
    L.h2(tr(lang, 'pdfH_missing'));
    const miss = missingList(snap, lang);
    if (miss.length) miss.forEach((m) => L.bullet(m));
    else L.textLine(tr(lang, 'pdfMissNone'), { color: MUTED });
    L.h2(tr(lang, 'pdfH_assume'));
    assumptions(snap, lang).forEach((m) => L.bullet(m));
    L.h2(tr(lang, 'pdfH_disc'));
    L.textLine(tr(lang, 'pdfDisclaimer'), { size: 10, lh: 14 });
    L.textLine(tr(lang, 'recDisclaimer'), { size: 10, lh: 14, color: MUTED });
  }

  async function buildPdf(snap) {
    if (!snap || !snap.farmId) throw fail('NO_FARM');
    if (!window.jspdf || !window.jspdf.jsPDF) throw fail('NO_LIB');
    if (!window.SFA_ARABIC) throw fail('NO_LIB');
    const lang = snap.lang === 'ar' ? 'ar' : 'en';
    const rtl = lang === 'ar';
    const fonts = await loadFonts();
    const doc = new window.jspdf.jsPDF({ unit: 'pt', format: 'a4', compress: true });
    // Arabic is already shaped/reordered by SFA_ARABIC. Do not reorder it a second time.
    const drawText = doc.text.bind(doc);
    doc.text = (value, x, y, options) => drawText(value, x, y, Object.assign({}, options,
      {isInputVisual: true, isOutputVisual: true, isInputRtl: false, isOutputRtl: false}));
    doc.addFileToVFS('Amiri-Regular.ttf', fonts.reg);
    doc.addFont('Amiri-Regular.ttf', FONT, 'normal');
    doc.addFileToVFS('Amiri-Bold.ttf', fonts.bold);
    doc.addFont('Amiri-Bold.ttf', FONT, 'bold');
    doc.setFont(FONT, 'normal');
    try { doc.setLanguage(lang === 'ar' ? 'ar-JO' : 'en-GB'); } catch (e) {}
    const L = layout(doc, rtl);
    fillBody(L, snap, lang);
    const pages = doc.getNumberOfPages();
    for (let i = 1; i <= pages; i++) {
      doc.setPage(i);
      paintChrome(doc, snap, lang, rtl, i, pages);
    }
    return doc;
  }

  function filename(snap) {
    const slug = String(snap.farmName || snap.farmId || 'farm').replace(/[^\w\u0600-\u06FF]+/g, '-').replace(/^-|-$/g, '');
    const day = String(snap.generatedAt || '').slice(0, 10);
    return 'smart-farm-report-' + slug + '-' + (snap.lang || 'en') + '-' + day + '.pdf';
  }

  window.SFA_REPORT = {
    cloneSnapshot(raw) { return clone(raw); },
    derivedFinance,
    async download(snap) {
      try {
        const frozen = clone(snap);
        if (!frozen || !frozen.farmId) throw fail('NO_FARM');
        frozen.generatedAt = frozen.generatedAt || new Date().toISOString();
        const doc = await buildPdf(frozen);
        doc.save(filename(frozen));
        return { ok: true, pages: doc.getNumberOfPages(), name: filename(frozen) };
      } catch (e) {
        if (e && e.code) throw e;
        throw fail('GEN_FAIL', e);
      }
    },
    /* Used by the local PDF test harness. */
    async blob(snap) {
      const doc = await buildPdf(clone(snap) || snap);
      return { blob: doc.output('blob'), name: filename(snap), pages: doc.getNumberOfPages(), doc };
    }
  };
})();
