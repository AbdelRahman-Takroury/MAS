/* Reusable recommendation component + resolver (SFA_REC).
 *
 * One shared structure (`Recommendation`, see types.js) holds text AND the
 * supporting values (`evidence`). Text may contain {key} placeholders that are
 * resolved from that evidence, so every consumer shows identical numbers:
 *   - dashboard dialog   -> SFA_REC.render(rec, lang)
 *   - audio (later)      -> SFA_REC.toPlainText(rec, lang)
 *   - PDF report -> SFA_REC.resolve(rec, lang)
 * No audio or PDF code lives here.
 */
(function () {
  const dict = () => window.SFA_I18N;
  const tr = (lang, k) => (dict()[lang][k] != null ? dict()[lang][k] : dict().en[k]) || k;
  const locale = (lang) => (lang === 'ar' ? 'ar-JO-u-nu-latn' : 'en-GB');
  const nf = (lang, n) => new Intl.NumberFormat(locale(lang), { maximumFractionDigits: 2 }).format(n);
  const isPair = (v) => v && typeof v === 'object' && !Array.isArray(v);

  /* Bilingual text pick with fallback to the other language (flagged). */
  function pick(v, lang) {
    if (isPair(v)) {
      if (v[lang]) return { text: String(v[lang]), lang, fallback: false };
      const o = lang === 'ar' ? 'en' : 'ar';
      if (v[o]) return { text: String(v[o]), lang: o, fallback: true };
      return { text: '', lang, fallback: false };
    }
    return { text: v == null ? '' : String(v), lang: null, fallback: false };
  }

  function fmtValue(e, lang) {
    const v = e.value;
    switch (e.unit) {
      case 'jod': return tr(lang, 'jod').replace('{n}', nf(lang, v));
      case 'dunum': return tr(lang, 'area').replace('{n}', nf(lang, v));
      case 'count': return nf(lang, v);
      case 'date': {
        const d = /^\d{4}-\d{2}-\d{2}$/.test(v) ? new Date(v + 'T12:00:00') : new Date(v);
        return isNaN(d) ? String(v) : new Intl.DateTimeFormat(locale(lang), { day: 'numeric', month: 'short', year: 'numeric' }).format(d);
      }
      case 'stage': case 'method': {
        const k = e.unit + '_' + String(v).toLowerCase(); const d = dict()[lang];
        return d[k] != null ? d[k] : String(v);
      }
      case 'text': return pick(v, lang).text;
      default: return typeof v === 'number' ? '\u2066' + nf(lang, v) + (e.unit ? ' ' + e.unit : '') + '\u2069' : String(v);
    }
  }
  function evLabel(e, lang) {
    if (isPair(e.label)) return pick(e.label, lang).text;
    const k = 'ev_' + e.key; return dict()[lang][k] != null ? dict()[lang][k] : e.key;
  }

  /* Resolve one recommendation into plain, language-specific content. */
  function resolve(rec, lang, opts) {
    /* opts.speech: Arabic spoken forms for values (numbers as words, units expanded). */
    const speech = !!(opts && opts.speech && lang === 'ar' && window.SFA_SPEECH);
    const fv = (e) => (speech
      ? window.SFA_SPEECH.formatEvidence(e, (v) => pick(v, 'ar').text, (u, v) => { const d = dict().ar[u + '_' + String(v).toLowerCase()]; return d != null ? d : String(v); })
      : fmtValue(e, lang));
    const ev = (rec.evidence || []).filter((e) => e && e.value != null && e.value !== '');
    const byKey = {}; ev.forEach((e) => { byKey[e.key] = e; });
    const fill = (p) => {
      const out = Object.assign({}, p);
      out.text = p.text.replace(/\{(\w+)\}/g, (m, k) => (byKey[k] ? fv(byKey[k]) : '—'));
      return out;
    };
    const f = (v) => fill(pick(v, lang));
    return {
      id: rec.id, farmId: rec.farmId || null, origin: rec.origin, lang,
      topic: rec.topic, topicLabel: dict()[lang]['topic_' + rec.topic] || rec.topic,
      summary: f(rec.summary), action: f(rec.action), why: f(rec.why),
      limitations: (rec.limitations || []).map(f).filter((x) => x.text),
      sources: (rec.sources || []).map((s) => ({ title: pick(s.title, lang), url: /^https?:\/\//i.test(s.url || '') ? s.url : null })).filter((s) => s.title.text),
      evidence: ev.map((e) => ({ key: e.key, label: evLabel(e, lang), value: fv(e) }))
    };
  }

  function toPlainText(rec, lang) {
    const r = resolve(rec, lang);
    const lines = [r.topicLabel, tr(lang, 'recSituation') + ': ' + r.summary.text, tr(lang, 'recAction') + ': ' + r.action.text, tr(lang, 'recWhy') + ': ' + r.why.text];
    if (r.limitations.length) lines.push(tr(lang, 'recLimits') + ': ' + r.limitations.map((l) => l.text).join(' '));
    return lines.join('\n');
  }

  /* DOM component. Classes reuse the dashboard's glass look. */
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function textEl(tag, cls, p) {
    const e = el(tag, cls, p.text);
    if (p.lang) { e.lang = p.lang; e.dir = p.lang === 'ar' ? 'rtl' : 'ltr'; }
    return e;
  }
  function render(rec, lang, opts) {
    const r = resolve(rec, lang);
    const card = el('article', 'rec-card'); card.dataset.topic = r.topic; card.dataset.recId = r.id;

    const head = el('header', 'rec-h');
    head.appendChild(el('h3', null, r.topicLabel));
    const tag = el('span', 'chip ' + (r.origin === 'api' ? 'live' : ''), r.origin === 'api' ? tr(lang, 'recFromApi') : r.origin === 'demo' ? tr(lang, 'recDemo') : tr(lang, 'sample'));
    head.appendChild(tag); card.appendChild(head);

    const sec = (key, content, cls) => {
      const s = el('section', 'rec-s ' + (cls || '')); s.appendChild(el('h4', null, tr(lang, key)));
      s.appendChild(content); card.appendChild(s);
    };
    sec('recSituation', textEl('p', null, r.summary));
    sec('recAction', textEl('p', 'rec-action', r.action), 'act');
    sec('recWhy', textEl('p', null, r.why));
    const ul = el('ul', 'rec-lims');
    if (r.limitations.length) r.limitations.forEach((l) => ul.appendChild(textEl('li', null, l)));
    else ul.appendChild(el('li', null, '–'));
    sec('recLimits', ul);

    const src = el('div');
    if (r.sources.length) {
      const l = el('ul', 'rec-src');
      r.sources.forEach((s) => {
        const li = el('li');
        if (s.url) { const a = textEl('a', null, s.title); a.href = s.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; li.appendChild(a); }
        else li.appendChild(textEl('span', null, s.title));
        l.appendChild(li);
      });
      src.appendChild(l);
    } else src.appendChild(el('p', 'muted', tr(lang, 'recNoSources')));
    sec('recSources', src);

    if (opts && opts.voice && window.SFA_VOICE) card.appendChild(window.SFA_VOICE.createPlayer(rec, opts.voice));

    if (r.evidence.length) {
      const basis = el('dl', 'rec-ev');
      r.evidence.forEach((e) => { const d = el('div'); d.appendChild(el('dt', null, e.label)); d.appendChild(el('dd', null, e.value)); basis.appendChild(d); });
      const wrap = el('footer', 'rec-basis'); wrap.appendChild(el('span', 'rb', tr(lang, 'recBasis'))); wrap.appendChild(basis);
      card.appendChild(wrap);
    }
    return card;
  }

  window.SFA_REC = { resolve, render, toPlainText, pick };
})();
