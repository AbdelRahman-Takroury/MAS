/* Shared data contracts (JSDoc only - no runtime code, not loaded by the page).
 * Reference for the dynamic dashboard, Arabic TTS and bilingual PDF features.
 * Every record carries `origin` so sample/demo data is never presented as real. */

/** @typedef {'api'|'sample'|'demo'} DataOrigin */

/**
 * @typedef {Object} ForecastDay
 * @property {string=} date            ISO date (YYYY-MM-DD)
 * @property {'sunny'|'partly'|'cloudy'|'rain'} condition
 * @property {number} high             degrees C
 * @property {number} low              degrees C
 * @property {number=} rain_mm
 */
/** @typedef {{origin: DataOrigin, date: string|null, source?: string|null, fetched_at?: string|null, days: ForecastDay[]}} Forecast */

/**
 * Per-farm sections served by SFA_API (see api.js for the assumed endpoints).
 * @typedef {{origin: DataOrigin, name: string|null, location: string|null, area_dunum: number|null,
 *            planting_date: string|null, crop_stage: string|null, irrigation_method: string|null}} FarmProfile
 * @typedef {{origin: DataOrigin, records: {date: string, confirmed: boolean}[],
 *            estimate: {value: number, unit: string}|null}} IrrigationData   only confirmed records are shown
 * @typedef {{origin: DataOrigin, recorded_costs_jod: number|null, projected_costs_jod: number|null,
 *            actual_revenue_jod: number|null, projected_revenue_jod: number|null,
 *            fertilizer_budget_jod: number|null, expected_harvest_kg?: number|null, actual_harvest_kg?: number|null,
 *            fertilizer_options?: {name: string|TextPair, cost_jod?: number|null}[]}} Financials   recorded/actual and projected are always separate
 * @typedef {{origin: DataOrigin, reminders: {id: *, title: string|{en: string, ar: string}, due_date?: string|null, reason?: string|{en: string, ar: string}|null}[]}} Inspections   reminders, NOT diagnoses
 */
/**
 * @typedef {Object} CropIndicator
 * @property {'growth'|'water'|'nutrient'|'weather'|'activity'} key
 * @property {'available'|'review'|'missing'} status
 */
/** @typedef {{origin: DataOrigin, indicators: CropIndicator[]}} CropOverview */

/**
 * A TextPair is bilingual text. A plain string is accepted but is shown as-is
 * (no language info); the frontend never translates or invents advice.
 * @typedef {{en: string, ar: string}} TextPair
 *
 * Supporting value behind a recommendation. Text may reference it with a
 * {key} placeholder, which SFA_REC resolves, so text and numbers never drift.
 * unit: 'jod' | 'dunum' | 'count' | 'date' | 'stage' | 'method' | 'text' (value is a TextPair) | any other unit string (e.g. 'mm')
 * @typedef {{key: string, value: number|string|TextPair, unit?: string, label?: TextPair}} Evidence
 *
 * THE shared recommendation structure - used by the dashboard dialog, the
 * audio interface and the PDF report (all through SFA_REC.resolve()).
 * Contract for Member 2: GET /farms/{id}/recommendations -> {recommendations: Recommendation[]}
 * Must NOT contain irrigation volumes/run times, fertilizer doses, disease probabilities or prices
 * unless produced by a reviewed backend calculation and supplied as `evidence`.
 * @typedef {Object} Recommendation
 * @property {string} id
 * @property {string=} farmId
 * @property {DataOrigin} origin               'api' | 'demo'  (demo = local rule-based sample)
 * @property {'irrigation'|'fertilizer'|'inspection'|'finance'|'data'} topic
 * @property {TextPair} summary                short farm situation
 * @property {TextPair} action                 suggested next action
 * @property {TextPair} why                    why it may be appropriate
 * @property {TextPair[]} limitations          missing information / limits
 * @property {{title: TextPair|string, url?: string}[]} sources
 * @property {Evidence[]} evidence
 */
/**
 * Frozen dashboard snapshot used by the PDF (js/report.js). Built in app.js
 * from the currently selected farm; recommendations are the same objects as
 * the dialog, rendered with SFA_REC.resolve(rec, lang).
 * @typedef {Object} ReportPayload
 * @property {string} generatedAt
 * @property {'en'|'ar'} lang
 * @property {boolean} live
 * @property {string|null} farmId
 * @property {string|null} farmName
 * @property {{status: string, data: FarmProfile|null}} profile
 * @property {{status: string, data: IrrigationData|null}=} irrigation
 * @property {{status: string, data: Financials|null}=} financials
 * @property {{status: string, data: Inspections|null}=} inspections
 * @property {{status: string, data: Forecast|null}=} weather
 * @property {{status: string, data: {origin: DataOrigin, recommendations: Recommendation[]}|null}} recs
 */
