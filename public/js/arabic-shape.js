/* Arabic joining + a simple RTL visual reorder for PDF engines that
 * draw left-to-right and do not run OpenType. Numbers and Latin runs
 * stay in logical (LTR) order inside an RTL line. */
(function () {
  'use strict';

  /* isolated, final, initial, medial. null initial/medial => right-joining only. */
  const F = {
    0x0621: [0xFE80, 0xFE80, null, null],
    0x0622: [0xFE81, 0xFE82, null, null],
    0x0623: [0xFE83, 0xFE84, null, null],
    0x0624: [0xFE85, 0xFE86, null, null],
    0x0625: [0xFE87, 0xFE88, null, null],
    0x0626: [0xFE89, 0xFE8A, 0xFE8B, 0xFE8C],
    0x0627: [0xFE8D, 0xFE8E, null, null],
    0x0628: [0xFE8F, 0xFE90, 0xFE91, 0xFE92],
    0x0629: [0xFE93, 0xFE94, null, null],
    0x062A: [0xFE95, 0xFE96, 0xFE97, 0xFE98],
    0x062B: [0xFE99, 0xFE9A, 0xFE9B, 0xFE9C],
    0x062C: [0xFE9D, 0xFE9E, 0xFE9F, 0xFEA0],
    0x062D: [0xFEA1, 0xFEA2, 0xFEA3, 0xFEA4],
    0x062E: [0xFEA5, 0xFEA6, 0xFEA7, 0xFEA8],
    0x062F: [0xFEA9, 0xFEAA, null, null],
    0x0630: [0xFEAB, 0xFEAC, null, null],
    0x0631: [0xFEAD, 0xFEAE, null, null],
    0x0632: [0xFEAF, 0xFEB0, null, null],
    0x0633: [0xFEB1, 0xFEB2, 0xFEB3, 0xFEB4],
    0x0634: [0xFEB5, 0xFEB6, 0xFEB7, 0xFEB8],
    0x0635: [0xFEB9, 0xFEBA, 0xFEBB, 0xFEBC],
    0x0636: [0xFEBD, 0xFEBE, 0xFEBF, 0xFEC0],
    0x0637: [0xFEC1, 0xFEC2, 0xFEC3, 0xFEC4],
    0x0638: [0xFEC5, 0xFEC6, 0xFEC7, 0xFEC8],
    0x0639: [0xFEC9, 0xFECA, 0xFECB, 0xFECC],
    0x063A: [0xFECD, 0xFECE, 0xFECF, 0xFED0],
    0x0641: [0xFED1, 0xFED2, 0xFED3, 0xFED4],
    0x0642: [0xFED5, 0xFED6, 0xFED7, 0xFED8],
    0x0643: [0xFED9, 0xFEDA, 0xFEDB, 0xFEDC],
    0x0644: [0xFEDD, 0xFEDE, 0xFEDF, 0xFEE0],
    0x0645: [0xFEE1, 0xFEE2, 0xFEE3, 0xFEE4],
    0x0646: [0xFEE5, 0xFEE6, 0xFEE7, 0xFEE8],
    0x0647: [0xFEE9, 0xFEEA, 0xFEEB, 0xFEEC],
    0x0648: [0xFEED, 0xFEEE, null, null],
    0x0649: [0xFEEF, 0xFEF0, null, null],
    0x064A: [0xFEF1, 0xFEF2, 0xFEF3, 0xFEF4],
    0x067E: [0xFB56, 0xFB57, 0xFB58, 0xFB59],
    0x0686: [0xFB7A, 0xFB7B, 0xFB7C, 0xFB7D],
    0x0698: [0xFB8A, 0xFB8B, null, null],
    0x06A9: [0xFB8E, 0xFB8F, 0xFB90, 0xFB91],
    0x06AF: [0xFB92, 0xFB93, 0xFB94, 0xFB95],
    0x06CC: [0xFBFC, 0xFBFD, 0xFBFE, 0xFBFF]
  };
  const LAM = 0x0644;
  const ALEF = { 0x0622: [0xFEF5, 0xFEF6], 0x0623: [0xFEF7, 0xFEF8], 0x0625: [0xFEF9, 0xFEFA], 0x0627: [0xFEFB, 0xFEFC] };
  const MARK = /[\u064B-\u065F\u0670\u06D6-\u06ED]/;
  const ZWJ = 0x200D;

  function isLetter(cp) { return !!F[cp] || cp === ZWJ; }
  function dual(cp) { return !!(F[cp] && F[cp][2] != null); }
  function nextLetter(cps, i) {
    for (let j = i + 1; j < cps.length; j++) {
      if (MARK.test(String.fromCodePoint(cps[j]))) continue;
      return cps[j];
    }
    return 0;
  }
  function prevLetter(cps, i) {
    for (let j = i - 1; j >= 0; j--) {
      if (MARK.test(String.fromCodePoint(cps[j]))) continue;
      return cps[j];
    }
    return 0;
  }

  function shapeArabic(text) {
    const cps = Array.from(String(text == null ? '' : text), (ch) => ch.codePointAt(0));
    const out = [];
    for (let i = 0; i < cps.length; i++) {
      const cp = cps[i];
      if (MARK.test(String.fromCodePoint(cp)) || !F[cp]) { out.push(cp); continue; }
      const prev = prevLetter(cps, i);
      const next = nextLetter(cps, i);
      const joinsPrev = dual(prev) || prev === ZWJ;
      if (cp === LAM && ALEF[next]) {
        const lig = ALEF[next];
        out.push(joinsPrev ? lig[1] : lig[0]);
        let skipped = false;
        for (let j = i + 1; j < cps.length; j++) {
          if (MARK.test(String.fromCodePoint(cps[j]))) { out.push(cps[j]); continue; }
          if (!skipped && cps[j] === next) { skipped = true; i = j; break; }
        }
        continue;
      }
      const forms = F[cp];
      const joinsNext = (dual(cp) && (dual(next) || ALEF[next] || F[next] || next === ZWJ)) && !!forms[2];
      let form = 0;
      if (joinsPrev && joinsNext) form = 3;
      else if (joinsPrev) form = 1;
      else if (joinsNext) form = 2;
      out.push(forms[form] != null ? forms[form] : forms[0]);
    }
    return String.fromCodePoint.apply(null, out);
  }

  function rtlChar(ch) {
    const cp = ch.codePointAt(0);
    return (cp >= 0x0590 && cp <= 0x08FF) || (cp >= 0xFB1D && cp <= 0xFDFF) || (cp >= 0xFE70 && cp <= 0xFEFF);
  }
  function ltrStrong(ch) {
    return /[A-Za-z0-9\u00B2\u00B3\u0660-\u0669\u06F0-\u06F9]/.test(ch);
  }

  /* RTL-base bidi: reverse RTL runs, keep LTR runs, reverse run order. */
  function toVisual(text) {
    const s = shapeArabic(String(text).replace(/[\u2066-\u2069\u200e\u200f]/g, ''));
    const chars = Array.from(s);
    const runs = [];
    let buf = '', kind = null;
    const flush = () => { if (buf) runs.push({ kind, buf }); buf = ''; };
    chars.forEach((ch) => {
      const k = rtlChar(ch) ? 'r' : (ltrStrong(ch) ? 'l' : 'n');
      if (kind == null) { kind = k; buf = ch; return; }
      if (k === kind || k === 'n' && kind !== 'l') { buf += ch; if (k !== 'n') kind = k; return; }
      if (kind === 'l' && k === 'n' && /[\s.,:/+\-%#?=]/.test(ch)) { buf += ch; return; }
      flush(); kind = k; buf = ch;
    });
    flush();
    const vis = [];
    for (let i = runs.length - 1; i >= 0; i--) {
      const r = runs[i];
      if (r.kind === 'l') {
        // Spaces at a logical run boundary move with that boundary in RTL.
        const leading = (r.buf.match(/^\s*/) || [''])[0];
        const trailing = (r.buf.match(/\s*$/) || [''])[0];
        vis.push(trailing + r.buf.trim() + leading);
      } else vis.push(Array.from(r.buf).reverse().join(''));
    }
    return vis.join('');
  }

  window.SFA_ARABIC = { shapeArabic, toVisual };
})();
