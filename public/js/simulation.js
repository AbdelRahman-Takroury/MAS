/* Presentation only: both baseline and scenario come from one server calculation. */
(function () {
  'use strict';
  const metrics = [
    ['water_budget', 'water_available_liters', 'Available water', 'المياه المتاحة', 'L'],
    ['water_budget', 'water_required_liters', 'Estimated water demand', 'الاحتياج المائي التقديري', 'L'],
    ['water_budget', 'water_shortage_liters', 'Estimated shortage', 'العجز التقديري', 'L'],
    ['finance', 'projected_total_cost_jod', 'Total projected costs', 'إجمالي التكاليف المتوقعة', 'JOD'],
    ['finance', 'projected_revenue_jod', 'Projected revenue', 'الإيراد المتوقع', 'JOD'],
    ['finance', 'projected_profit_jod', 'Projected profit', 'الربح المتوقع', 'JOD'],
    ['finance', 'break_even_jod_per_kg', 'Break-even price', 'سعر التعادل', 'JOD/kg']
  ];
  const text = (lang, en, ar) => lang === 'ar' ? ar : en;
  const finite = (v) => typeof v === 'number' && Number.isFinite(v) ? v : null;
  function format(value, unit, lang) {
    if (value === null) return text(lang, 'Unavailable', 'غير متاح');
    const amount = new Intl.NumberFormat(lang === 'ar' ? 'ar-JO-u-nu-latn' : 'en-GB',
      { maximumFractionDigits: unit === 'JOD/kg' ? 4 : 3 }).format(value);
    const suffix = lang === 'ar' ? {L: 'لتر', JOD: 'دينار', 'JOD/kg': 'دينار/كغم'}[unit] : unit;
    return amount + ' ' + suffix;
  }
  function view(result, lang) {
    if (!result || result.persisted !== false || !result.water_budget || !result.finance || !result.baseline) {
      throw new Error('INVALID_SIMULATION');
    }
    return metrics.map(([section, key, en, ar, unit]) => {
      const before = finite((result.baseline[section] || {})[key]);
      const after = finite((result[section] || {})[key]);
      const delta = before === null || after === null ? null : Number((after - before).toFixed(unit === 'JOD/kg' ? 4 : 3));
      return {key, title: text(lang, en, ar), before, after, delta,
        baseline: format(before, unit, lang), simulated: format(after, unit, lang),
        difference: delta === null ? text(lang, 'Difference unavailable', 'الفرق غير متاح') :
          delta === 0 ? text(lang, 'No change', 'دون تغيير') :
          text(lang, delta > 0 ? 'Increase: ' : 'Decrease: ', delta > 0 ? 'زيادة: ' : 'انخفاض: ') + format(Math.abs(delta), unit, lang)};
    });
  }
  function render(container, result, lang) {
    const rows = view(result, lang);
    container.replaceChildren();
    const el = (tag, value, cls) => { const n = document.createElement(tag); n.textContent = value; if (cls) n.className = cls; return n; };
    container.appendChild(el('h3', text(lang, 'Simulation comparison', 'مقارنة المحاكاة')));
    container.appendChild(el('p', text(lang,
      'Not saved. These results do not change farm records or predict yield changes caused by water shortage.',
      'لم يتم الحفظ. هذه النتائج لا تغير سجلات المزرعة ولا تتنبأ بتغير المحصول بسبب عجز المياه.'), 'sim-note'));
    if (result.baseline.water_budget && result.baseline.water_budget.availability_source === 'seeded_demo') {
      container.appendChild(el('p', text(lang, 'Baseline water is a seeded demo value.', 'المياه في خط الأساس قيمة تجريبية.'), 'sim-note'));
    }
    const grid = el('div', '', 'sim-grid');
    rows.forEach((row) => {
      const card = el('article', '', 'sim-card'); card.dataset.metric = row.key;
      card.appendChild(el('h4', row.title));
      const dl = el('dl', '');
      [[text(lang, 'Baseline', 'خط الأساس'), row.baseline], [text(lang, 'Simulated', 'المحاكاة'), row.simulated]].forEach(([label, value]) => {
        const pair = el('div', ''); pair.append(el('dt', label), el('dd', value)); dl.appendChild(pair);
      });
      card.append(dl, el('p', row.difference, 'sim-difference')); grid.appendChild(card);
    });
    container.appendChild(grid);
    container.appendChild(el('p', text(lang,
      'Both columns use the same forecast. Unavailable values require more inputs; this comparison is advisory.',
      'يستخدم العمودان التنبؤ نفسه. القيم غير المتاحة تحتاج مدخلات إضافية؛ هذه المقارنة للمساعدة في اتخاذ القرار.'), 'sim-note'));
  }
  function errorMessage(error, lang) {
    if (error && error.status === 422) return text(lang,
      'Check the simulation inputs. Enter at least one finite, non-negative value. Blank fields keep the baseline.',
      'تحقق من مدخلات المحاكاة. أدخل قيمة واحدة على الأقل، محدودة وغير سالبة. الحقول الفارغة تبقي خط الأساس.');
    if (error && error.status === 404) return text(lang, 'Farm not found. Select an existing farm.', 'المزرعة غير موجودة. اختر مزرعة موجودة.');
    return text(lang, 'Simulation could not be completed. Your records were not changed; you can retry.',
      'تعذر إكمال المحاكاة. لم تتغير سجلاتك؛ يمكنك إعادة المحاولة.');
  }
  window.SFA_SIMULATION = {view, render, errorMessage};
})();
