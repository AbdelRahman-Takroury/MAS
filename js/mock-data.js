/* DEMONSTRATION DATA ONLY.
 * Everything here is illustrative. The UI labels it "Sample data" whenever the
 * service returns it (origin: 'sample'). Three scenarios exist so the dynamic
 * dashboard can be exercised: complete data, missing fields, and API failures.
 * `errors` lists sections the mock service will reject, to test error states. */
(function () {
  const BASE_DATE = '2026-10-09';
  const days = (arr) => ({
    date: BASE_DATE,
    days: arr.map((a) => ({ condition: a[0], high: a[1], low: a[2], rain_mm: a[3] }))
  });

  window.SFA_MOCK = {
    forecastDate: BASE_DATE,
    farms: {
      a: {
        label: 'Sample A – complete data',
        errors: [],
        profile: { name: 'Tomato Plot A1', location: 'Jordan Valley (sample)', area_dunum: 4, planting_date: '2026-08-20', crop_stage: 'vegetative', irrigation_method: 'drip' },
        irrigation: {
          records: [
            { date: '2026-10-07', confirmed: true },
            { date: '2026-10-09', confirmed: false } // unconfirmed: must NOT count
          ],
          estimate: { value: 18, unit: 'mm', basis: 'sample' }
        },
        financials: { recorded_costs_jod: 1240, projected_costs_jod: 3100, actual_revenue_jod: 0, projected_revenue_jod: 5200, fertilizer_budget_jod: 380 },
        inspections: { reminders: [{ id: 1, title: { en: 'Inspect lower leaves', ar: 'افحص الأوراق السفلية' } }, { id: 2, title: { en: 'Check drip lines', ar: 'تفقد خطوط التنقيط' } }] },
        weather: days([['sunny', 33, 20, 0], ['sunny', 34, 21, 0], ['partly', 32, 20, 0], ['partly', 30, 19, 0], ['cloudy', 28, 18, 1], ['rain', 26, 17, 4], ['partly', 29, 18, 0]])
      },
      b: {
        label: 'Sample B – missing fields',
        errors: [],
        profile: { name: 'Tomato Plot B2', location: null, area_dunum: null, planting_date: null, crop_stage: null, irrigation_method: null },
        irrigation: { records: [], estimate: null },
        financials: { recorded_costs_jod: 420, projected_costs_jod: null, actual_revenue_jod: null, projected_revenue_jod: null, fertilizer_budget_jod: null },
        inspections: { reminders: [] },
        weather: { date: BASE_DATE, days: [] }
      },
      c: {
        label: 'Sample C – API errors',
        errors: ['irrigation', 'financials', 'weather'],
        profile: { name: 'Tomato Plot C3', location: 'Jordan Valley (sample)', area_dunum: 2.5, planting_date: '2026-09-15', crop_stage: 'flowering', irrigation_method: 'drip' },
        irrigation: null, financials: null, weather: null,
        inspections: { reminders: [{ id: 3, title: { en: 'Inspect flowers', ar: 'افحص الأزهار' } }] }
      }
    }
  };
})();
