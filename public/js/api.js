/* Centralised frontend API service (the only module that talks to the backend).
 *
 * API_BASE defaults to null and serves clearly-tagged sample data. Connect the
 * FastAPI backend at any time with SFA_API.configure({ API_BASE: '/api' }).
 * With API_BASE set, failures surface as errors - never replaced by sample data.
 *
 * Implemented API contract:
 *   GET/POST /farms; GET/PUT/PATCH/DELETE /farms/{id}
 *   GET/POST /farms/{id}/irrigation; CRUD /farms/{id}/irrigation/{record_id}
 *   GET/POST /farms/{id}/expenses; POST /farms/{id}/costs (compatibility alias)
 *   GET/POST /farms/{id}/harvests; GET/POST /farms/{id}/sales
 *   GET/POST /farms/{id}/seasons; CRUD /farms/{id}/seasons/{season_id}
 *   GET /farms/{id}                  -> {name, location, area_dunum, planting_date, crop_stage, irrigation_method, origin}
 *   GET  /farms/{id}/irrigation       -> {records:[{date, confirmed}], estimate:{value, unit}|null}
   *   GET  /farms/{id}/financials       -> {recorded_costs_jod, projected_costs_jod, actual_revenue_jod,
 *                                         projected_revenue_jod, fertilizer_budget_jod,
 *                                         expected_harvest_kg?, actual_harvest_kg?,
 *                                         fertilizer_options?:[{name|title, cost_jod?}]}
   *   GET  /farms/{id}/inspections      -> {reminders:[{id, title:string|{en,ar}, due_date?, reason?:string|{en,ar}}]}
   *   GET  /farms/{id}/weather          -> {date, source?, fetched_at?, days:[{date?, condition, high, low, rain_mm?}]}
 *   GET  /farms/{id}/recommendations  -> {recommendations:[Recommendation]}   (see types.js; text fields are {en, ar},
 *                                         {placeholders} resolved from each item's evidence; NO doses/volumes/prices)
 *   POST /assistant/voice             -> {audio_url, text, voice_id, demo_mode?}   (see docs/voice-backend-contract.md)
 *   GET  {audio_url}                  -> audio bytes (same origin as API_BASE, same auth)
 *   POST /farms/{id}/irrigation       (write)  -> refreshes ['irrigation']
 *   POST /farms/{id}/costs            (write)  -> refreshes ['financials']
 *   PATCH /farms/{id}                 (write)  -> refreshes ['profile','weather']
 *   POST /assistant/chat              -> {answer, sources?:[{title, url}]}
 * Weather, inspections, recommendations, chat, and voice routes are compatible
 * endpoints; integrations without configured providers return empty data or
 * explicit 503 errors. The frontend only displays calculated backend values.
 *
 * Successful writes dispatch `sfa:data-updated` ({detail:{farmId, sections}});
 * the dashboard listens and refetches only those sections. Writes are never
 * faked in sample mode.
 */
(function () {
  /* Optional: window.SFA_CONFIG.getAuthHeaders = () => ({ Authorization: 'Bearer ...' }) for protected endpoints. */
  const cfg = Object.assign({ API_BASE: null, getAuthHeaders: null }, window.SFA_CONFIG || {});
  const pendingWrites = new Map();
  const retryKeys = new Map();
  let operationGeneration = 0;
  function beginNewOperation() { operationGeneration += 1; retryKeys.clear(); }

  const authHeaders = () => (typeof cfg.getAuthHeaders === 'function' ? cfg.getAuthHeaders() || {} : {});
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const live = () => !!cfg.API_BASE;
  const num = (v) => (typeof v === 'number' && isFinite(v) ? v : null);
  const str = (v) => (typeof v === 'string' && v.trim() ? v.trim() : null);
  const enc = encodeURIComponent;
  const VOICE_ID = 'ar-JO-TaimNeural'; // required voice; the backend must use exactly this

  async function http(path, opts) {
    opts = opts || {};
    const headers = Object.assign({ 'Content-Type': 'application/json', Accept: 'application/json' }, authHeaders(), opts.headers || {});
    const request = Object.assign({}, opts, { headers });
    const res = await fetch(cfg.API_BASE.replace(/\/$/, '') + path, request);
    if (!res.ok) {
      let detail; try { detail = (await res.json()).detail; } catch (_) {}
      const err = new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((x) => x.loc.join('.') + ': ' + x.msg).join('; ') : 'HTTP ' + res.status);
      err.status = res.status; throw err;
    }
    return res.status === 204 ? {} : res.json();
  }

  function mockFarm(id) {
    const f = window.SFA_MOCK.farms[id];
    if (!f) throw new Error('Unknown sample farm');
    return f;
  }
  async function mockSection(id, section) {
    await sleep(250 + Math.random() * 250);
    const f = mockFarm(id);
    if (f.errors.indexOf(section) !== -1 || !f[section]) throw new Error('Simulated API error: ' + section);
    return f[section];
  }
  function notifyUpdated(sections, farmId) {
    window.dispatchEvent(new CustomEvent('sfa:data-updated', { detail: { farmId: farmId || null, sections: sections || null } }));
  }
  async function write(path, method, body, sections, farmId) {
    if (!live()) throw new Error('NO_BACKEND'); // never fake a successful write
    // Object property order must not change the identity of a retry.
    const stable = (value) => Array.isArray(value) ? value.map(stable) :
      value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])])) : value;
    const serialized = JSON.stringify(stable(body));
    const flightKey = cfg.API_BASE + ':' + operationGeneration + ':' + method + ':' + path + ':' + serialized;
    if (pendingWrites.has(flightKey)) return pendingWrites.get(flightKey);
    const createKey = retryKeys.get(flightKey) || (body && body.idempotency_key ? body.idempotency_key :
      (window.crypto && typeof window.crypto.randomUUID === 'function' ? window.crypto.randomUUID() : 'sfa-' + Date.now() + '-' + Math.random().toString(36).slice(2)));
    retryKeys.set(flightKey, createKey);
    const opts = { method, headers: { 'Idempotency-Key': createKey } };
    if (body != null) opts.body = serialized;
    const request = http(path, opts)
      .then((r) => { retryKeys.delete(flightKey); notifyUpdated(sections, farmId); return r; })
      .catch((error) => {
        // Network, decoding, timeout and server errors may follow a committed write.
        if (error.status >= 400 && error.status < 500 && ![408, 425, 429].includes(error.status)) retryKeys.delete(flightKey);
        throw error;
      });
    pendingWrites.set(flightKey, request);
    try { return await request; }
    finally { pendingWrites.delete(flightKey); }
  }

  window.SFA_API = {
    isLive: live,
    beginNewOperation,
    configure(options) {
      if (!options || typeof options !== 'object') throw new TypeError('API configuration must be an object');
      if (Object.prototype.hasOwnProperty.call(options, 'API_BASE') && options.API_BASE != null && typeof options.API_BASE !== 'string') throw new TypeError('API_BASE must be a URL string or null');
      Object.assign(cfg, options);
      return { API_BASE: cfg.API_BASE, live: live() };
    },
    notifyUpdated,
    simulate: (id, overrides) => http('/farms/' + enc(id) + '/simulate', { method: 'POST', body: JSON.stringify({ overrides }) }),

    async getFarms() {
      if (!live()) {
        await sleep(150);
        return { origin: 'sample', farms: Object.keys(window.SFA_MOCK.farms).map((id) => ({ id, name: window.SFA_MOCK.farms[id].profile.name, label: window.SFA_MOCK.farms[id].label })) };
      }
      const d = await http('/farms');
      const list = Array.isArray(d) ? d : Array.isArray(d.farms) ? d.farms : [];
      return { origin: d.origin === 'sample' ? 'sample' : 'api', farms: list.map((x) => ({ id: String(x.id), name: str(x.name), label: str(x.label), origin: x.origin || d.origin || 'api' })) };
    },

    async getFarm(id) {
      if (!live()) { const p = await mockSection(id, 'profile'); return Object.assign({ origin: 'sample' }, p); }
      const d = await http('/farms/' + enc(id));
      return {
        origin: d.origin === 'sample' ? 'sample' : 'api', name: str(d.name), location: str(d.location), area_dunum: num(d.area_dunum),
        planting_date: str(d.planting_date), crop_stage: str(d.crop_stage), irrigation_method: str(d.irrigation_method),
        latitude: num(d.latitude), longitude: num(d.longitude), irrigation_efficiency: num(d.irrigation_efficiency),
        effective_rain_fraction: num(d.effective_rain_fraction),
        establishment_method: str(d.establishment_method), system_flow_liters_per_hour: num(d.system_flow_liters_per_hour)
      };
    },

    async getIrrigation(id) {
      let d, origin = 'api';
      if (!live()) { d = await mockSection(id, 'irrigation'); origin = 'sample'; } else d = await http('/farms/' + enc(id) + '/irrigation');
      const e = d.estimate;
      const est = e ? { value: num(e.value), unit: str(e.unit) || '', status: str(e.status), partial_total: num(e.partial_total),
        partial_coverage: e.partial_coverage && typeof e.partial_coverage === 'object' ? e.partial_coverage : null,
        period_days: num(e.period_days), missing_inputs: Array.isArray(e.missing_inputs) ? e.missing_inputs : [],
        basis: str(e.basis), basis_ar: str(e.basis_ar), warnings: Array.isArray(e.warnings) ? e.warnings : [],
        warnings_ar: Array.isArray(e.warnings_ar) ? e.warnings_ar : [], assumptions: Array.isArray(e.assumptions) ? e.assumptions : [],
        weather_status: str(e.weather_status), weather_source: str(e.weather_source), weather_fetched_at: str(e.weather_fetched_at) } : null;
      return { origin: d.origin === 'sample' ? 'sample' : origin, records: Array.isArray(d.records) ? d.records : [], estimate: est, water_budget: d.water_budget || null };
    },

    async getFinancials(id) {
      let d, origin = 'api';
      if (!live()) { d = await mockSection(id, 'financials'); origin = 'sample'; } else d = await http('/farms/' + enc(id) + '/financials');
      const opts = Array.isArray(d.fertilizer_options) ? d.fertilizer_options.map((x) => ({
        name: x && (x.name || x.title) ? x.name || x.title : null,
        cost_jod: x ? num(x.cost_jod) : null
      })).filter((x) => x.name) : [];
      return {
        origin: d.origin === 'sample' ? 'sample' : origin,
        recorded_costs_jod: num(d.recorded_costs_jod), projected_costs_jod: num(d.projected_costs_jod),
        actual_revenue_jod: num(d.actual_revenue_jod), projected_revenue_jod: num(d.projected_revenue_jod),
        fertilizer_budget_jod: num(d.fertilizer_budget_jod),
        expected_harvest_kg: num(d.expected_harvest_kg), actual_harvest_kg: num(d.actual_harvest_kg),
        expected_harvest_source: str(d.expected_harvest_source), expected_harvest_scope: str(d.expected_harvest_scope),
        actual_harvest_source: str(d.actual_harvest_source), actual_harvest_scope: str(d.actual_harvest_scope),
        actual_harvest_active_season_kg: num(d.actual_harvest_active_season_kg),
        actual_sold_kg: num(d.actual_sold_kg), actual_cost_per_sold_kg_jod: num(d.actual_cost_per_sold_kg_jod),
        actual_break_even_jod_per_kg: num(d.actual_break_even_jod_per_kg),
        calculation_warnings: Array.isArray(d.calculation_warnings) ? d.calculation_warnings : [],
        fertilizer_options: opts,
        server_calculated: d.server_calculated === true,
        projected_profit_jod: num(d.projected_profit_jod), actual_profit_jod: num(d.actual_profit_jod),
        cost_per_kg_jod: num(d.cost_per_kg_jod), cost_per_kg_recorded_jod: num(d.cost_per_kg_recorded_jod),
        break_even_price_jod: num(d.break_even_price_jod)
      };
    },

    async getFertilizers(id) {
      if (!live()) return { origin: 'unavailable', updated_at: null, source: null, budget_jod: null, notice: null, products: [] };
      const d = await http('/farms/' + enc(id) + '/fertilizers');
      return {
        origin: str(d.origin) || 'api', updated_at: str(d.updated_at), source: str(d.source),
        farm_id: str(d.farm_id), farm_name: str(d.farm_name), budget_jod: num(d.budget_jod),
        budget_origin: str(d.budget_origin), notice: str(d.notice), notice_ar: str(d.notice_ar),
        products: Array.isArray(d.products) ? d.products.filter((p) => p && p.id && p.source_url).map((p) => ({
          id: str(p.id), name: str(p.name), name_ar: str(p.name_ar), analysis: str(p.analysis),
          package_quantity: num(p.package_quantity), package_unit: str(p.package_unit),
          price_jod: num(p.price_jod), price_per_kg_jod: num(p.price_per_kg_jod),
          source: str(p.source), source_url: str(p.source_url), source_updated: str(p.source_updated),
          source_fit: str(p.source_fit), source_fit_ar: str(p.source_fit_ar),
          profile: str(p.profile), profile_ar: str(p.profile_ar), budget_jod: num(p.budget_jod),
          budget_remaining_after_one_pack_jod: num(p.budget_remaining_after_one_pack_jod),
          within_budget_for_one_pack: typeof p.within_budget_for_one_pack === 'boolean' ? p.within_budget_for_one_pack : null
        })) : []
      };
    },

    async getInspections(id) {
      let d, origin = 'api';
      if (!live()) { d = await mockSection(id, 'inspections'); origin = 'sample'; } else d = await http('/farms/' + enc(id) + '/inspections');
      return {
        origin: d.origin === 'sample' ? 'sample' : origin,
        reminders: (Array.isArray(d.reminders) ? d.reminders : []).map((r) => ({
          id: r && r.id, title: r && r.title, due_date: r && str(r.due_date), reason: r && r.reason ? r.reason : null
        }))
      };
    },

    async getForecast(id) {
      let d, origin = 'api';
      if (!live()) { d = await mockSection(id, 'weather'); origin = 'sample'; } else d = await http('/farms/' + enc(id) + '/weather');
      return {
        origin: d.origin === 'sample' ? 'sample' : origin, date: str(d.date), source: str(d.source), fetched_at: str(d.fetched_at),
        weather_status: str(d.status), coverage_status: str(d.coverage_status), coverage: d.coverage || null, warnings: Array.isArray(d.warnings) ? d.warnings : [],
        errors: Array.isArray(d.errors) ? d.errors : [], missing_inputs: Array.isArray(d.missing_inputs) ? d.missing_inputs : [],
        days: Array.isArray(d.days) ? d.days.slice(0, 7) : []
      };
    },

    /* Personalised recommendations for one farm. Live: backend results.
     * Sample mode: rule-based DEMO built from that farm's sample sections
     * (origin 'demo') - never an AI answer. */
    async getRecommendations(id) {
      if (!live()) {
        await sleep(350);
        const f = mockFarm(id), ok = (s) => (f.errors.indexOf(s) === -1 && f[s] ? f[s] : null);
        return { origin: 'demo', recommendations: window.SFA_DEMO_RECS({
          farmId: id, profile: ok('profile'), irrigation: ok('irrigation'), financials: ok('financials'),
          inspections: ok('inspections'), weather: ok('weather')
        }) };
      }
      const d = await http('/farms/' + enc(id) + '/recommendations');
      const list = Array.isArray(d.recommendations) ? d.recommendations : [];
      const arr = (v) => (Array.isArray(v) ? v : []);
      return {
        origin: d.origin === 'sample' ? 'sample' : 'api',
        recommendations: list.filter((r) => r && r.topic && r.action).map((r, i) => ({
          id: String(r.id || id + '-' + i), farmId: id, origin: d.origin === 'sample' ? 'sample' : 'api', topic: String(r.topic),
          summary: r.summary || '', action: r.action, why: r.why || '',
          limitations: arr(r.limitations), sources: arr(r.sources), evidence: arr(r.evidence)
        }))
      };
    },

    /* Arabic voice (Azure AI Speech, voice ar-JO-TaimNeural) - generated ONLY by the backend.
     * Returns { blob, text, voiceId, demoMode }. Throws Error with .code:
     * NO_BACKEND | AUTH | NOT_FOUND | UNCONFIGURED | VOICE_MISMATCH | NETWORK | BAD_AUDIO
     * No audio is ever fabricated on the client. */
    async requestVoice(recommendationId, farmId) {
      const fail = (code, e) => { const x = new Error(code); x.code = code; x.cause = e; return x; };
      if (!live()) throw fail('NO_BACKEND');
      let meta;
      try {
        meta = await http('/assistant/voice', { method: 'POST', credentials: 'include', body: JSON.stringify({ recommendation_id: recommendationId, language: 'ar-JO', voice_id: VOICE_ID, farm_id: farmId || null }) });
      } catch (e) {
        if (e.status === 401 || e.status === 403) throw fail('AUTH', e);
        if (e.status === 404 || e.status === 422) throw fail('NOT_FOUND', e);
        if (e.status === 503 || e.status === 501) throw fail('UNCONFIGURED', e);
        throw fail('NETWORK', e);
      }
      if (meta.voice_id && meta.voice_id !== VOICE_ID) throw fail('VOICE_MISMATCH'); // never accept a different voice silently
      let url, apiUrl;
      try { apiUrl = new URL(cfg.API_BASE, location.href); url = new URL(String(meta.audio_url || ''), apiUrl); } catch (e) { throw fail('BAD_AUDIO', e); }
      if (url.origin !== apiUrl.origin) throw fail('BAD_AUDIO'); // never send credentials elsewhere
      let blob;
      try {
        const res = await fetch(url.href, { credentials: 'include', headers: authHeaders() });
        if (res.status === 401 || res.status === 403) throw fail('AUTH');
        if (!res.ok) throw fail('NETWORK');
        blob = await res.blob();
      } catch (e) { throw e.code ? e : fail('NETWORK', e); }
      if (!blob || !blob.size || !/^audio\//i.test(blob.type)) throw fail('BAD_AUDIO');
      return { blob, text: str(meta.text), voiceId: VOICE_ID, demoMode: meta.demo_mode === true };
    },

    /* Writes (live backend only). */
    recordIrrigation: (id, payload) => write('/farms/' + enc(id) + '/irrigation', 'POST', payload, ['irrigation'], id),
    recordCost: (id, payload) => write('/farms/' + enc(id) + '/costs', 'POST', payload, ['financials'], id),
    updateFarm: (id, payload) => write('/farms/' + enc(id), 'PATCH', payload, null, id),
    createFarm: (payload) => write('/farms', 'POST', payload, null, null),
    deleteFarm: (id) => write('/farms/' + enc(id), 'DELETE', null, null, null),
    getSeasons: (id) => http('/farms/' + enc(id) + '/seasons'),
    createSeason: (id, payload) => write('/farms/' + enc(id) + '/seasons', 'POST', payload, null, id),
    updateSeason: (id, seasonId, payload) => write('/farms/' + enc(id) + '/seasons/' + enc(seasonId), 'PATCH', payload, null, id),
    deleteSeason: (id, seasonId) => write('/farms/' + enc(id) + '/seasons/' + enc(seasonId), 'DELETE', null, null, id),
    updateIrrigation: (id, recordId, payload) => write('/farms/' + enc(id) + '/irrigation/' + enc(recordId), 'PATCH', payload, ['irrigation'], id),
    deleteIrrigation: (id, recordId) => write('/farms/' + enc(id) + '/irrigation/' + enc(recordId), 'DELETE', null, ['irrigation'], id),
    getExpenses: (id) => http('/farms/' + enc(id) + '/expenses'),
    createExpense: (id, payload) => write('/farms/' + enc(id) + '/expenses', 'POST', payload, ['financials'], id),
    updateExpense: (id, recordId, payload) => write('/farms/' + enc(id) + '/expenses/' + enc(recordId), 'PATCH', payload, ['financials'], id),
    deleteExpense: (id, recordId) => write('/farms/' + enc(id) + '/expenses/' + enc(recordId), 'DELETE', null, ['financials'], id),
    getHarvests: (id) => http('/farms/' + enc(id) + '/harvests'),
    recordHarvest: (id, payload) => write('/farms/' + enc(id) + '/harvests', 'POST', payload, ['financials'], id),
    updateHarvest: (id, recordId, payload) => write('/farms/' + enc(id) + '/harvests/' + enc(recordId), 'PATCH', payload, ['financials'], id),
    deleteHarvest: (id, recordId) => write('/farms/' + enc(id) + '/harvests/' + enc(recordId), 'DELETE', null, ['financials'], id),
    getSales: (id) => http('/farms/' + enc(id) + '/sales'),
    recordSale: (id, payload) => write('/farms/' + enc(id) + '/sales', 'POST', payload, ['financials'], id),
    updateSale: (id, recordId, payload) => write('/farms/' + enc(id) + '/sales/' + enc(recordId), 'PATCH', payload, ['financials'], id),
    deleteSale: (id, recordId) => write('/farms/' + enc(id) + '/sales/' + enc(recordId), 'DELETE', null, ['financials'], id),

    /* Returns { answer, sources[], origin: 'api' | 'demo' } */
    async askAssistant(message, lang, farmId) {
      if (!live()) {
        await sleep(900);
        return { origin: 'demo', answer: window.SFA_DEMO_ANSWER(message, lang), sources: [] };
      }
      const d = await http('/assistant/chat', { method: 'POST', body: JSON.stringify({ message, language: lang, farm_id: farmId || null }) });
      return { origin: d.origin === 'fallback' ? 'fallback' : 'api', answer: String(d.answer || ''), sources: Array.isArray(d.sources) ? d.sources : [] };
    }
  };
})();
