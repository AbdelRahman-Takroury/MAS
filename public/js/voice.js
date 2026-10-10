/* Arabic voice player for recommendation cards (SFA_VOICE).
 *
 * Plays REAL audio that the backend generated with Microsoft Azure AI Speech
 * (voice ar-JO-TaimNeural) via SFA_API.requestVoice(). Nothing is simulated:
 * with no backend the player shows a clear Arabic error + retry. The browser
 * speechSynthesis voice is offered only as an explicitly labelled, optional,
 * lower-quality fallback and is never the default.
 *
 * Behaviour: one request per recommendation at a time (de-duplicated), one
 * audio playing at a time, blob URLs revoked on reset/pagehide, players torn
 * down whenever their cards are re-rendered or the dialog closes.
 */
(function () {
  'use strict';
  const I = () => window.SFA_I18N;
  const tl = (lang, k) => (I()[lang] && I()[lang][k] != null ? I()[lang][k] : I().en[k]) || k;
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const svgIcon = (id) => {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('width', 16); s.setAttribute('height', 16); s.setAttribute('aria-hidden', 'true');
    const u = document.createElementNS('http://www.w3.org/2000/svg', 'use'); u.setAttribute('href', '#' + id); s.appendChild(u); return s;
  };
  const fmtTime = (s) => (isFinite(s) ? Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0') : '–:––');

  const cache = new Map();     // key -> { url, text, demoMode }
  const inflight = new Map();  // key -> Promise (prevents duplicate generation)
  const players = new Set();
  let current = null, gen = 0;

  function fetchVoice(rec, farmId) {
    const key = farmId + '|' + rec.id;
    if (cache.has(key)) return Promise.resolve(cache.get(key));
    if (inflight.has(key)) return inflight.get(key);
    const my = gen;
    const p = window.SFA_API.requestVoice(rec.id, farmId).then((r) => {
      const entry = { url: URL.createObjectURL(r.blob), text: r.text, demoMode: r.demoMode };
      if (my !== gen) { URL.revokeObjectURL(entry.url); const e = new Error('NETWORK'); e.code = 'NETWORK'; throw e; } // data changed meanwhile
      cache.set(key, entry); return entry;
    }).finally(() => inflight.delete(key));
    inflight.set(key, p);
    return p;
  }

  function createPlayer(rec, opts) {
    const lang = (opts && opts.lang) || 'ar', farmId = (opts && opts.farmId) || '';
    const en = lang === 'en';
    const speech = window.SFA_SPEECH.fromRecommendation(rec);
    let status = 'idle', audio = null, entry = null, usingBrowser = false, destroyed = false;

    const root = el('section', 'voice'); root.setAttribute('aria-label', tl('ar', 'v_listen'));

    /* primary action */
    const listen = el('button', 'v-listen'); listen.type = 'button';
    const ic = svgIcon('i-speaker'); listen.appendChild(ic);
    const lt = el('span', 'v-label'); const ar = el('span', null, tl('ar', 'v_listen')); ar.lang = 'ar'; ar.dir = 'rtl'; lt.appendChild(ar);
    if (en) lt.appendChild(el('small', null, tl('en', 'v_listen_en')));
    listen.appendChild(lt);
    listen.disabled = !speech.available;
    root.appendChild(listen);

    /* transport controls (shown when real audio is ready) */
    const ctr = el('div', 'v-ctr'); ctr.hidden = true;
    const toggle = el('button', 'v-btn'); toggle.type = 'button';
    const stop = el('button', 'v-btn'); stop.type = 'button'; stop.appendChild(svgIcon('i-stop'));
    const replay = el('button', 'v-btn'); replay.type = 'button'; replay.appendChild(svgIcon('i-replay'));
    const seek = el('input', 'v-seek'); seek.type = 'range'; seek.min = 0; seek.max = 1000; seek.value = 0; seek.step = 1; seek.disabled = true;
    const time = el('span', 'v-time', '0:00 / –:––'); time.dir = 'ltr';
    const lab = (b, k) => { b.setAttribute('aria-label', tl(lang, k)); b.title = tl(lang, k); };
    lab(stop, 'v_stop'); lab(replay, 'v_replay'); seek.setAttribute('aria-label', tl(lang, 'v_progress'));
    ctr.append(toggle, stop, replay, seek, time); root.appendChild(ctr);

    /* status / errors / fallback */
    const msg = el('div', 'v-msg'); msg.setAttribute('role', 'status'); msg.setAttribute('aria-live', 'polite'); root.appendChild(msg);
    const acts = el('div', 'v-acts'); acts.hidden = true;
    const retry = el('button', 'retry'); retry.type = 'button'; retry.textContent = tl(lang, 'retry') + (en ? '' : '');
    if (!en) retry.textContent = tl('ar', 'v_retry');
    const browser = el('button', 'v-alt'); browser.type = 'button'; browser.textContent = tl(lang, 'v_browser');
    acts.append(retry, browser); root.appendChild(acts);
    const meta = el('p', 'v-meta'); meta.hidden = true; root.appendChild(meta);

    /* transcript - always visible, Arabic */
    const tr = el('figure', 'v-tr');
    const trl = el('figcaption', null, tl(lang, 'v_transcript'));
    const trb = el('blockquote'); trb.lang = 'ar'; trb.dir = 'rtl';
    const trn = el('p', 'v-trnote');
    tr.append(trl, trb, trn); root.appendChild(tr);
    if (speech.available) { trb.textContent = speech.text; trn.textContent = tl(lang, 'v_preview'); }
    else { trb.textContent = tl('ar', 'v_no_text'); trn.textContent = en ? tl('en', 'v_no_text') : ''; }
    root.appendChild(el('p', 'v-foot', tl(lang, 'v_footer')));

    /* ---- helpers ---- */
    function showMsg(kind, code) {
      msg.replaceChildren(); msg.className = 'v-msg ' + (kind || '');
      if (kind === 'load') { msg.appendChild(el('i', 'v-spin')); const s = el('span', null, tl('ar', 'v_loading')); s.lang = 'ar'; s.dir = 'rtl'; msg.appendChild(s); if (en) msg.appendChild(el('small', null, tl('en', 'v_loading'))); }
      else if (kind === 'err') {
        const k = 'v_err_' + code;
        const a = el('p', null, tl('ar', k)); a.lang = 'ar'; a.dir = 'rtl'; msg.appendChild(a);
        if (en) msg.appendChild(el('p', 'v-en', tl('en', k)));
      } else if (kind === 'info') { const s = el('p', null, tl(lang, code)); msg.appendChild(s); }
    }
    function sync() {
      const playing = audio && !audio.paused && !audio.ended;
      const ended = audio && audio.ended;
      toggle.replaceChildren(svgIcon(playing ? 'i-pause' : 'i-play'));
      const k = playing ? 'v_pause' : (audio && audio.currentTime > 0 && !ended ? 'v_resume' : 'v_play'); lab(toggle, k);
      root.classList.toggle('playing', !!playing);
      if (audio) {
        const d = audio.duration, c = audio.currentTime;
        time.textContent = fmtTime(c) + ' / ' + fmtTime(d);
        seek.disabled = !isFinite(d) || d <= 0;
        if (!seek.disabled && document.activeElement !== seek) seek.value = Math.round((c / d) * 1000);
        seek.setAttribute('aria-valuetext', fmtTime(c) + ' / ' + fmtTime(d));
      }
    }
    function setStatus(s) {
      status = s; listen.disabled = !speech.available || s === 'loading';
      listen.hidden = s === 'ready' || s === 'browser';
      ctr.hidden = s !== 'ready';
      root.classList.toggle('busy', s === 'loading');
      acts.hidden = s !== 'error';
      if (s !== 'browser') toggle.hidden = replay.hidden = seek.hidden = time.hidden = false;
    }
    function pauseOthers() { players.forEach((p) => { if (p !== api) p.pause(); }); }

    function attach(e) {
      if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
      audio = new Audio(); audio.preload = 'metadata'; audio.src = e.url;
      ['timeupdate', 'loadedmetadata', 'durationchange', 'play', 'pause', 'ended'].forEach((ev) => audio.addEventListener(ev, sync));
      audio.addEventListener('error', () => { if (!destroyed) fail('BAD_AUDIO'); });
    }
    function fail(code) {
      if (audio) { audio.pause(); }
      if (code === 'BAD_AUDIO') {
        const key = farmId + '|' + rec.id;
        const cached = cache.get(key); if (cached) URL.revokeObjectURL(cached.url);
        cache.delete(key); entry = null;
      }
      setStatus('error'); showMsg('err', code);
      browser.hidden = !('speechSynthesis' in window) || !speech.available;
    }

    async function start() {
      if (status === 'loading' || !speech.available) return;
      usingBrowser = false; if ('speechSynthesis' in window) speechSynthesis.cancel();
      setStatus('loading'); showMsg('load');
      try {
        entry = await fetchVoice(rec, farmId);
        if (destroyed) return;
        attach(entry);
        if (entry.text) { trb.textContent = entry.text; trn.textContent = tl(lang, 'v_final'); }
        meta.hidden = false; meta.textContent = tl(lang, 'v_voice') + ': Azure AI Speech · ar-JO-TaimNeural' + (entry.demoMode ? ' · ' + tl(lang, 'v_demo') : '');
        setStatus('ready'); showMsg(''); sync();
        pauseOthers(); current = api;
        try { await audio.play(); } catch (e) { /* user can press play */ }
        sync();
      } catch (e) { if (!destroyed) fail((e && e.code) || 'NETWORK'); }
    }
    function speakBrowser() {
      if (!speech.available || !('speechSynthesis' in window)) { showMsg('err', 'nobrowser'); return; }
      const voices = speechSynthesis.getVoices();
      if (!voices.some((v) => /^ar/i.test(v.lang))) { showMsg('err', 'nobrowser'); return; }
      pauseOthers(); speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(speech.text); u.lang = 'ar-JO';
      const v = voices.find((x) => /^ar-JO/i.test(x.lang)) || voices.find((x) => /^ar/i.test(x.lang)); if (v) u.voice = v;
      u.onend = () => { if (usingBrowser && !destroyed) { usingBrowser = false; setStatus('error'); showMsg('info', 'v_browser_done'); } };
      u.onerror = () => { if (usingBrowser && !destroyed) { usingBrowser = false; fail('nobrowser'); } };
      usingBrowser = true; setStatus('browser'); acts.hidden = true; showMsg('info', 'v_browser_on');
      stop.disabled = false; ctr.hidden = false; toggle.hidden = true; replay.hidden = true; seek.hidden = true; time.hidden = true;
      speechSynthesis.speak(u); current = api;
    }

    /* ---- events ---- */
    listen.addEventListener('click', start);
    retry.addEventListener('click', () => { entry = null; start(); });
    browser.addEventListener('click', speakBrowser);
    toggle.addEventListener('click', () => {
      if (!audio) return;
      if (audio.paused || audio.ended) { pauseOthers(); current = api; if (audio.ended) audio.currentTime = 0; audio.play().catch(() => fail('BAD_AUDIO')); } else audio.pause();
    });
    stop.addEventListener('click', () => {
      if (usingBrowser) { usingBrowser = false; speechSynthesis.cancel(); setStatus('error'); showMsg(''); toggle.hidden = replay.hidden = seek.hidden = time.hidden = false; return; }
      if (audio) { audio.pause(); audio.currentTime = 0; sync(); }
    });
    replay.addEventListener('click', () => { if (!audio) return; pauseOthers(); current = api; audio.currentTime = 0; audio.play().catch(() => fail('BAD_AUDIO')); });
    seek.addEventListener('input', () => { if (audio && isFinite(audio.duration)) audio.currentTime = (seek.value / 1000) * audio.duration; });

    const api = {
      pause() { if (audio && !audio.paused) audio.pause(); if (usingBrowser) { usingBrowser = false; speechSynthesis.cancel(); setStatus('error'); showMsg(''); toggle.hidden = replay.hidden = seek.hidden = time.hidden = false; } },
      destroy() {
        destroyed = true; players.delete(api);
        if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); audio = null; }
        if (usingBrowser && 'speechSynthesis' in window) speechSynthesis.cancel();
        if (current === api) current = null;
      }
    };
    players.add(api); toggle.replaceChildren(svgIcon('i-play')); lab(toggle, 'v_play');
    return root;
  }

  function revokeAll() { cache.forEach((e) => URL.revokeObjectURL(e.url)); cache.clear(); }
  window.SFA_VOICE = {
    createPlayer,
    stopAll() { players.forEach((p) => p.pause()); },
    destroyPlayers() { Array.from(players).forEach((p) => p.destroy()); },
    /* Call when farm data changes: stops everything and drops cached audio. */
    reset() { gen++; Array.from(players).forEach((p) => p.destroy()); revokeAll(); }
  };
  window.addEventListener('pagehide', () => { window.SFA_VOICE.destroyPlayers(); revokeAll(); });
})();
