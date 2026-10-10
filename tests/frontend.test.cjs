const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

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
