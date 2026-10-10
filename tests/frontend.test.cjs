const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('simulation preserves unavailable values, zero, units and neutral differences in both languages', () => {
  const sim = load('simulation.js').window.SFA_SIMULATION;
  const result = {persisted: false, baseline: {water_budget: {water_available_liters: null, water_required_liters: 2500, water_shortage_liters: null},
    finance: {projected_total_cost_jod: 12.345, projected_profit_jod: -10, break_even_jod_per_kg: .1234}},
    water_budget: {water_available_liters: 0, water_required_liters: 2500, water_shortage_liters: 2500},
    finance: {projected_total_cost_jod: 22.345, projected_profit_jod: -5, break_even_jod_per_kg: .2234}};
  for (const lang of ['ar', 'en']) {
    const rows = sim.view(result, lang);
    assert.equal(rows.length, 7);
    assert.equal(rows[0].before, null);
    assert.equal(rows[0].after, 0);
    assert.equal(rows[0].delta, null);
    assert.equal(rows[1].delta, 0);
    assert.equal(rows[3].delta, 10);
    assert.match(rows[6].simulated, /0\.2234/);
    assert.match(rows[0].baseline, lang === 'ar' ? /غير متاح/ : /Unavailable/);
  }
  assert.throws(() => sim.view({}, 'en'), /INVALID_SIMULATION/);
  assert.throws(() => sim.view({...result, persisted: true}, 'en'), /INVALID_SIMULATION/);
});

test('simulation validation, unknown farm and backend errors have bilingual recovery messages', () => {
  const sim = load('simulation.js').window.SFA_SIMULATION;
  assert.match(sim.errorMessage({status: 422}, 'en'), /non-negative/);
  assert.match(sim.errorMessage({status: 422}, 'ar'), /غير سالبة/);
  assert.match(sim.errorMessage({status: 404}, 'en'), /Farm not found/);
  assert.match(sim.errorMessage({status: 503}, 'ar'), /إعادة المحاولة/);
});

function load(file, extras = {}) {
  const context = vm.createContext({window: {}, console, ...extras});
  vm.runInContext(readFileSync(path.join(__dirname, '../public/js', file), 'utf8'), context);
  return context;
}

test('live PDF finance uses server values, never recalculates with remaining harvest as total', () => {
  const context = load('report.js');
  const result = context.window.SFA_REPORT.derivedFinance({server_calculated: true, expected_harvest_kg: 100,
    projected_costs_jod: 300, projected_revenue_jod: 500, projected_profit_jod: 200,
    actual_profit_jod: -10, cost_per_kg_jod: 1.5, break_even_price_jod: 1.5});
  assert.equal(result.break_even_price_jod, 1.5);
  assert.equal(result.cost_per_kg_jod, 1.5);
  assert.equal(result.projected_profit_jod, 200);
  assert.equal(result.cost_per_kg_recorded_jod, null);
});

test('sample report retains explicit demo calculations', () => {
  const context = load('report.js');
  const result = context.window.SFA_REPORT.derivedFinance({expected_harvest_kg: 100, projected_costs_jod: 300, projected_revenue_jod: 500});
  assert.equal(result.break_even_price_jod, 3);
  assert.equal(result.projected_profit_jod, 200);
});

test('frontend preserves server fallback and sample provenance', async () => {
  const context = load('api.js', {window: {SFA_CONFIG: {API_BASE: '/api/ui'}}, fetch: async () => ({ok: true, status: 200,
    json: async () => ({origin: 'fallback', answer: 'Safe fallback', sources: [{title: 'Source', url: 'https://example.org'}]})})});
  const reply = await context.window.SFA_API.askAssistant('water', 'en', 'farm');
  assert.equal(reply.origin, 'fallback');
  assert.equal(reply.sources.length, 1);
});

test('backend error is surfaced, not replaced by sample data', async () => {
  const context = load('api.js', {window: {SFA_CONFIG: {API_BASE: '/api/ui'}}, fetch: async () => ({ok: false, status: 503, json: async () => ({detail: 'Database unavailable'})})});
  await assert.rejects(context.window.SFA_API.getFinancials('farm'), /Database unavailable/);
});

test('frontend carries authoritative finance metrics into report snapshot', async () => {
  const context = load('api.js', {window: {SFA_CONFIG: {API_BASE: '/api/ui'}}, fetch: async () => ({ok: true, status: 200,
    json: async () => ({server_calculated: true, origin: 'sample', break_even_price_jod: .1234, actual_profit_jod: -5})})});
  const result = await context.window.SFA_API.getFinancials('farm');
  assert.equal(result.server_calculated, true);
  assert.equal(result.break_even_price_jod, .1234);
  assert.equal(result.actual_profit_jod, -5);
  assert.equal(result.origin, 'sample');
});


function writeClient(fetch) {
  let id = 0;
  return load('api.js', {window: {SFA_CONFIG: {API_BASE: '/api/ui'},
    crypto: {randomUUID: () => 'key-' + ++id}, dispatchEvent: () => {}},
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } }, fetch}).window.SFA_API;
}
const writePayload = {date: '2026-09-01', category: 'labor', amount_jod: 10};
const savedResponse = () => ({ok: true, status: 201, json: async () => ({id: 'saved'})});

for (const failure of ['network', 'server', 'decode']) {
  test('retry retains key after uncertain ' + failure + ' result, success starts a new operation', async () => {
    const keys = [];
    const api = writeClient(async (_, options) => {
      keys.push(options.headers['Idempotency-Key']);
      if (keys.length === 1) {
        if (failure === 'network') throw new TypeError('Lost response');
        if (failure === 'server') return {ok: false, status: 503, json: async () => ({detail: 'Unknown outcome'})};
        return {ok: true, status: 201, json: async () => { throw new SyntaxError('Truncated response'); }};
      }
      return savedResponse();
    });
    await assert.rejects(api.createExpense('farm', writePayload));
    await api.createExpense('farm', {...writePayload});
    assert.equal(keys[0], keys[1]);
    await api.createExpense('farm', {...writePayload});
    assert.notEqual(keys[1], keys[2]);
  });
}

test('explicit new operation and changed payload do not reuse an uncertain key', async () => {
  const keys = [];
  const api = writeClient(async (_, options) => { keys.push(options.headers['Idempotency-Key']); throw new TypeError('Lost response'); });
  await assert.rejects(api.createExpense('farm', writePayload));
  await assert.rejects(api.createExpense('farm', {...writePayload, amount_jod: 20}));
  api.beginNewOperation();
  await assert.rejects(api.createExpense('farm', writePayload));
  assert.equal(new Set(keys).size, 3);
});

test('simultaneous identical frontend writes share one request', async () => {
  let calls = 0, release;
  const api = writeClient(async () => { calls++; await new Promise(resolve => { release = resolve; }); return savedResponse(); });
  const first = api.createExpense('farm', writePayload);
  const second = api.createExpense('farm', {...writePayload});
  assert.equal(calls, 1);
  release();
  assert.deepEqual(await first, await second);
});

test('definitive validation failure releases the key', async () => {
  const keys = [];
  const api = writeClient(async (_, options) => {
    keys.push(options.headers['Idempotency-Key']);
    return {ok: false, status: 422, json: async () => ({detail: 'Invalid data'})};
  });
  await assert.rejects(api.createExpense('farm', writePayload));
  await assert.rejects(api.createExpense('farm', writePayload));
  assert.notEqual(keys[0], keys[1]);
});


test('reordered object properties retain the uncertain request key', async () => {
  const keys = [];
  const api = writeClient(async (_, options) => { keys.push(options.headers['Idempotency-Key']); throw new TypeError('Lost response'); });
  await assert.rejects(api.createExpense('farm', writePayload));
  await assert.rejects(api.createExpense('farm', {amount_jod: 10, category: 'labor', date: '2026-09-01'}));
  assert.equal(keys[0], keys[1]);
});


test('weather API preserves partial coverage, missing fields and cached provenance', async () => {
  const context = load('api.js', {window: {SFA_CONFIG: {API_BASE: '/api/ui'}}, fetch: async () => ({ok: true, status: 200,
    json: async () => ({status: 'cached', coverage_status: 'partial', coverage: {requested_days: 7, complete_days: 6},
      source: 'open-meteo', fetched_at: '2026-10-10T10:00:00Z', missing_inputs: ['2026-10-10:et0_mm'],
      warnings: ['Partial forecast'], days: []})})});
  const data = await context.window.SFA_API.getForecast('farm');
  assert.equal(data.weather_status, 'cached');
  assert.equal(data.coverage_status, 'partial');
  assert.equal(data.coverage.complete_days, 6);
  assert.equal(data.missing_inputs[0], '2026-10-10:et0_mm');
  assert.equal(data.fetched_at, '2026-10-10T10:00:00Z');
});

test('irrigation API preserves unknown allocation as null and explicit zero as zero', async () => {
  for (const amount of [null, 0]) {
    const context = load('api.js', {window: {SFA_CONFIG: {API_BASE: '/api/ui'}}, fetch: async () => ({ok: true, status: 200,
      json: async () => ({records: [], estimate: null, water_budget: {water_available_liters: amount, water_shortage_liters: null}})})});
    const data = await context.window.SFA_API.getIrrigation('farm');
    assert.equal(data.water_budget.water_available_liters, amount);
    assert.equal(data.water_budget.water_shortage_liters, null);
  }
});


test('recommendation evidence preserves monetary precision and Arabic units', () => {
  const context = load('i18n.js');
  vm.runInContext(readFileSync(path.join(__dirname, '../public/js/recommendation-card.js'), 'utf8'), context);
  const rec = {
    id: 'farm-review', topic: 'finance', summary: {en: 'Estimate', ar: 'تقدير'},
    action: {en: 'Review', ar: 'راجع'}, why: {en: 'Recorded data', ar: 'بيانات مسجلة'},
    limitations: [], sources: [], evidence: [
      {key: 'break_even', label: {en: 'Break-even', ar: 'سعر التعادل'}, value: 0.1234, unit: 'jod/kg'},
      {key: 'recorded_expenses', label: {en: 'Expenses', ar: 'المصروفات'}, value: 12.345, unit: 'jod'},
      {key: 'water_availability', label: {en: 'Available water', ar: 'المياه المتاحة'},
       value: {en: 'unknown', ar: 'غير معروفة'}, unit: 'text'},
    ],
  };
  const ar = context.window.SFA_REC.resolve(rec, 'ar');
  assert.match(ar.evidence[0].value, /0\.1234 دينار\/كغم/);
  assert.match(ar.evidence[1].value, /12\.345/);
  assert.equal(ar.evidence[2].value, 'غير معروفة');
});

