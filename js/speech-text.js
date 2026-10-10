/* Arabic spoken-text preparation (SFA_SPEECH).
 *
 * Turns a resolved recommendation into clear, short Arabic sentences for the
 * voice: numbers, money, dates, temperatures and units become spoken words.
 * It never adds advice - it only re-formats text and values that already
 * exist in the recommendation, and it never guesses missing values.
 *
 * Used for the visible transcript PREVIEW. The authoritative spoken text must
 * come from the backend (`text` in the /assistant/voice response) so the audio
 * and transcript always match; the backend should port these rules.
 * No audio is produced here.
 */
(function () {
  const ONES_M = ['صفر', 'واحد', 'اثنان', 'ثلاثة', 'أربعة', 'خمسة', 'ستة', 'سبعة', 'ثمانية', 'تسعة', 'عشرة'];
  const ONES_F = ['صفر', 'واحدة', 'اثنتان', 'ثلاث', 'أربع', 'خمس', 'ست', 'سبع', 'ثماني', 'تسع', 'عشر'];
  const TEENS_M = ['', 'أحد عشر', 'اثنا عشر', 'ثلاثة عشر', 'أربعة عشر', 'خمسة عشر', 'ستة عشر', 'سبعة عشر', 'ثمانية عشر', 'تسعة عشر'];
  const TEENS_F = ['', 'إحدى عشرة', 'اثنتا عشرة', 'ثلاث عشرة', 'أربع عشرة', 'خمس عشرة', 'ست عشرة', 'سبع عشرة', 'ثماني عشرة', 'تسع عشرة'];
  const TENS = { 2: 'عشرون', 3: 'ثلاثون', 4: 'أربعون', 5: 'خمسون', 6: 'ستون', 7: 'سبعون', 8: 'ثمانون', 9: 'تسعون' };
  const HUNDREDS = ['', 'مئة', 'مئتان', 'ثلاثمئة', 'أربعمئة', 'خمسمئة', 'ستمئة', 'سبعمئة', 'ثمانمئة', 'تسعمئة'];
  const MONTHS = ['كانون الثاني', 'شباط', 'آذار', 'نيسان', 'أيار', 'حزيران', 'تموز', 'آب', 'أيلول', 'تشرين الأول', 'تشرين الثاني', 'كانون الأول'];
  const ORD = ['', 'الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن', 'التاسع', 'العاشر', 'الحادي عشر', 'الثاني عشر', 'الثالث عشر',
    'الرابع عشر', 'الخامس عشر', 'السادس عشر', 'السابع عشر', 'الثامن عشر', 'التاسع عشر', 'العشرون', 'الحادي والعشرون', 'الثاني والعشرون', 'الثالث والعشرون',
    'الرابع والعشرون', 'الخامس والعشرون', 'السادس والعشرون', 'السابع والعشرون', 'الثامن والعشرون', 'التاسع والعشرون', 'الثلاثون', 'الحادي والثلاثون'];

  function under100(n, fem) {
    if (n <= 10) return (fem ? ONES_F : ONES_M)[n];
    if (n < 20) return (fem ? TEENS_F : TEENS_M)[n - 10];
    const o = n % 10, t = Math.floor(n / 10);
    return o ? (fem ? ONES_F : ONES_M)[o] + ' و' + TENS[t] : TENS[t];
  }
  function under1000(n, fem) {
    const h = Math.floor(n / 100), r = n % 100, parts = [];
    if (h) parts.push(HUNDREDS[h]);
    if (r) parts.push(under100(r, fem));
    return parts.join(' و');
  }
  /* Whole numbers up to 999,999,999. fem = counted noun is feminine. */
  function cardinal(n, fem) {
    if (n === 0) return 'صفر';
    const parts = [];
    const m = Math.floor(n / 1e6), th = Math.floor((n % 1e6) / 1000), rest = n % 1000;
    if (m) parts.push(m === 1 ? 'مليون' : m === 2 ? 'مليونان' : m <= 10 ? ONES_M[m] + ' ملايين' : under1000(m, false) + ' مليون');
    if (th) parts.push(th === 1 ? 'ألف' : th === 2 ? 'ألفان' : th <= 10 ? ONES_M[th] + ' آلاف' : under1000(th, false) + ' ألف');
    if (rest) parts.push(under1000(rest, fem));
    return parts.join(' و');
  }
  /* Genitive/accusative forms (after "عام", "من"). */
  function genitive(s) {
    return s.replace(/ألفان/g, 'ألفين').replace(/مئتان/g, 'مئتين').replace(/اثنان/g, 'اثنين').replace(/اثنتان/g, 'اثنتين').replace(/(\S)ون(?=\s|$)/g, '$1ين');
  }

  function parseNum(s) {
    const clean = String(s).replace(/,/g, '');
    if (!/^\d+(\.\d+)?$/.test(clean)) return null;
    const [i, d] = clean.split('.');
    return { int: Number(i), dec: d || null, isInt: !d };
  }
  function numberWords(p, fem) {
    let s = cardinal(p.int, fem);
    if (p.dec) s += ' فاصل ' + p.dec.split('').map((c) => ONES_M[Number(c)]).join(' ');
    return s;
  }

  /* Unit phrases: one / two / few (3-10) / many (11+ and decimals). */
  const UNITS = {
    jod: { one: 'دينار أردني واحد', two: 'ديناران أردنيان', few: 'دنانير أردنية', many: 'دينار أردني' },
    c: { fem: true, one: 'درجة مئوية واحدة', two: 'درجتان مئويتان', few: 'درجات مئوية', many: 'درجة مئوية' },
    mm: { one: 'ملّيمتر واحد', two: 'ملّيمتران', few: 'ملّيمترات', many: 'ملّيمتر' },
    dunum: { one: 'دونم واحد', two: 'دونمان', few: 'دونمات', many: 'دونم' },
    kg: { one: 'كيلوغرام واحد', two: 'كيلوغرامان', few: 'كيلوغرامات', many: 'كيلوغرام' },
    l: { one: 'لتر واحد', two: 'لتران', few: 'لترات', many: 'لتر' },
    pct: { simple: 'بالمئة' },
    m3: { simple: 'متر مكعب' }
  };
  function quantity(numStr, unitKey) {
    const p = parseNum(numStr); if (!p) return null;
    const u = UNITS[unitKey];
    if (u.simple) return numberWords(p, false) + ' ' + u.simple;
    if (!p.isInt) return numberWords(p, !!u.fem) + ' ' + u.many;
    const n = p.int;
    if (n === 1) return u.one;
    if (n === 2) return u.two;
    if (n >= 3 && n <= 10) return cardinal(n, !!u.fem) + ' ' + u.few;
    return cardinal(n, !!u.fem) + ' ' + u.many;
  }
  function spokenDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso); if (!m) return null;
    const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]);
    if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
    return ORD[d] + ' من ' + MONTHS[mo - 1] + ' عام ' + genitive(cardinal(y, false));
  }

  const N = '(\\d[\\d,]*(?:\\.\\d+)?)';
  const RULES = [
    [/(\d{4}-\d{2}-\d{2})/g, (m, d) => spokenDate(d) || m],
    [new RegExp(N + '\\s*(?:°\\s*C|℃|°)', 'g'), (m, n) => quantity(n, 'c') || m],
    [new RegExp(N + '\\s*%', 'g'), (m, n) => quantity(n, 'pct') || m],
    [new RegExp('(?:JOD|JD)\\s*' + N, 'g'), (m, n) => quantity(n, 'jod') || m],
    [new RegExp(N + '\\s*(?:JOD|JD|د\\.أ|دينار(?:\\s+أردني)?)', 'g'), (m, n) => quantity(n, 'jod') || m],
    [new RegExp(N + '\\s*(?:mm|ملم|ملليمتر|ملّيمتر)(?![A-Za-z])', 'g'), (m, n) => quantity(n, 'mm') || m],
    [new RegExp(N + '\\s*(?:dunums?|دونم)', 'g'), (m, n) => quantity(n, 'dunum') || m],
    [new RegExp(N + '\\s*(?:kg|كغم|كجم)(?![A-Za-z])', 'g'), (m, n) => quantity(n, 'kg') || m],
    [new RegExp(N + '\\s*(?:L|liters?|لتر)(?![A-Za-z])', 'g'), (m, n) => quantity(n, 'l') || m],
    [new RegExp(N + '\\s*(?:m³|m3)', 'g'), (m, n) => quantity(n, 'm3') || m]
  ];

  const toLatinDigits = (s) => s.replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));

  /* Free text: digits + units -> Arabic words. Plain remaining numbers are read as cardinals. */
  function normalizeNumbers(text) {
    let s = toLatinDigits(String(text));
    RULES.forEach(([re, fn]) => { s = s.replace(re, fn); });
    s = s.replace(/\d[\d,]*(?:\.\d+)?/g, (m) => { const p = parseNum(m); return p ? numberWords(p, false) : m; });
    return s;
  }

  /* Evidence value -> spoken Arabic (used by SFA_REC in speech mode). */
  function formatEvidence(e, pickText, enumLabel) {
    const v = e.value;
    switch (e.unit) {
      case 'jod': return quantity(String(v), 'jod') || String(v);
      case 'dunum': return quantity(String(v), 'dunum') || String(v);
      case 'count': { const p = parseNum(String(v)); return p ? numberWords(p, false) : String(v); }
      case 'date': return spokenDate(String(v)) || String(v);
      case 'stage': case 'method': return enumLabel(e.unit, v);
      case 'text': return normalizeNumbers(pickText(v));
      case 'mm': return quantity(String(v), 'mm') || String(v);
      default: {
        const key = { '°C': 'c', '%': 'pct', kg: 'kg', L: 'l', 'm3': 'm3', 'm³': 'm3' }[e.unit];
        return typeof v === 'number' && key ? quantity(String(v), key) : normalizeNumbers(String(v) + (e.unit ? ' ' + e.unit : ''));
      }
    }
  }

  /* Clean a sentence for speech: no URLs, ids, braces, markup, bidi marks. */
  function clean(text) {
    return normalizeNumbers(text)
      .replace(/[\u2066-\u2069\u200e\u200f]/g, '')
      .replace(/https?:\/\/\S+/g, '')
      .replace(/\{[^}]*\}/g, '')
      .replace(/[<>*_#`|\\[\]]/g, ' ')
      .replace(/\s*[()]\s*/g, '، ')
      .replace(/\s*:\s*/g, '، ')
      .replace(/—/g, '')
      .replace(/\s+،/g, '،').replace(/،\s*،/g, '،')
      .replace(/\s+/g, ' ').trim();
  }
  function splitSentences(text) {
    const out = [];
    clean(text).split(/(?<=[.!؟?])\s+/).forEach((s) => {
      s = s.trim().replace(/^،\s*/, ''); if (!s) return;
      while (s.length > 170) {
        const cut = s.lastIndexOf('،', 120);
        if (cut < 40) break;
        out.push(s.slice(0, cut).trim() + '.'); s = s.slice(cut + 1).trim();
      }
      out.push(/[.!؟?]$/.test(s) ? s : s + '.');
    });
    return out;
  }

  /* Build the Arabic spoken text from a shared Recommendation. */
  function fromRecommendation(rec) {
    const r = window.SFA_REC.resolve(rec, 'ar', { speech: true });
    const ok = (p) => p && p.text && !p.fallback; // never read English text with the Arabic voice
    const head = (t) => [t + '.'];
    let sentences = [];
    if (ok(r.summary)) sentences = sentences.concat(head('وضع المزرعة'), splitSentences(r.summary.text));
    if (ok(r.action)) sentences = sentences.concat(head('الخطوة المقترحة'), splitSentences(r.action.text));
    if (ok(r.why)) sentences = sentences.concat(head('السبب'), splitSentences(r.why.text));
    const lims = r.limitations.filter(ok);
    if (lims.length) { sentences.push('ملاحظات مهمة.'); lims.forEach((l) => { sentences = sentences.concat(splitSentences(l.text)); }); }
    if (rec.origin === 'demo') sentences.push('هذه توصية تجريبية وليست نصيحة زراعية معتمدة.');
    const hasCore = ok(r.summary) || ok(r.action);
    return { available: hasCore, text: hasCore ? sentences.join(' ') : '', sentences: hasCore ? sentences : [] };
  }

  window.SFA_SPEECH = { cardinal, quantity, spokenDate, normalizeNumbers, formatEvidence, splitSentences, fromRecommendation };
})();
