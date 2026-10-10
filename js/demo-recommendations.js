/* DEMO recommendation generator (not an AI model).
 *
 * Used only by SFA_API when no backend is connected. It reads one farm's
 * section data (the same sample data the dashboard shows) and builds
 * structured recommendations with rules - so every farm gets different
 * content, and values come from `evidence`, never from typed-in numbers.
 * It produces NO irrigation quantities, fertilizer doses, disease
 * probabilities or market prices.
 *
 * Output follows the shared `Recommendation` shape (see types.js).
 * Placeholders like {recorded_costs_jod} are resolved by SFA_REC from the
 * recommendation's own `evidence`, so text and numbers cannot drift apart.
 *
 * Input: { farmId, profile, irrigation, financials, inspections, weather }
 * where any failed section is null.
 */
(function () {
  const T = (en, ar) => ({ en, ar });

  window.SFA_DEMO_RECS = function (inp) {
    const P = inp.profile, IR = inp.irrigation, FN = inp.financials, IN = inp.inspections, WX = inp.weather;
    const sampleNote = T('This is based on sample data, not real farm records.', 'هذا مبني على بيانات تجريبية وليس سجلات مزرعة حقيقية.');
    const recs = [];
    const make = (topic, r) => {
      recs.push({
        id: inp.farmId + '-' + topic, farmId: inp.farmId, origin: 'demo', topic,
        summary: r.summary, action: r.action, why: r.why,
        limitations: [sampleNote].concat(r.limitations || []),
        sources: [], evidence: r.evidence || []
      });
    };
    const ev = (arr, key, value, unit) => { if (value != null && value !== '') arr.push({ key, value, unit }); };

    /* ---- Irrigation ---- */
    if (!IR) {
      make('irrigation', {
        summary: T('Irrigation data could not be loaded for this farm.', 'ما قدرنا نحمّل بيانات الري لهذه المزرعة.'),
        action: T('Refresh the data, then review the irrigation records.', 'جرّب تحديث البيانات، وبعدها راجع سجل الري.'),
        why: T('This recommendation needs the irrigation records.', 'هذه التوصية بتحتاج سجل الري.'),
        limitations: [T('No irrigation information is available right now.', 'ما في معلومات ري متوفرة حالياً.')]
      });
    } else {
      const confirmed = IR.records.filter((r) => r.confirmed === true && r.date).sort((a, b) => String(b.date).localeCompare(String(a.date)));
      const unconfirmed = IR.records.length - IR.records.filter((r) => r.confirmed === true).length;
      const e = [];
      ev(e, 'last_irrigation', confirmed[0] && confirmed[0].date, 'date');
      if (IR.estimate) ev(e, 'irrigation_estimate', IR.estimate.value, IR.estimate.unit);
      ev(e, 'irrigation_method', P && P.irrigation_method, 'method');
      const rainDays = WX && WX.days ? WX.days.filter((d) => d.rain_mm > 0).length : 0;
      if (rainDays) ev(e, 'forecast_rain_days', rainDays, 'count');
      const lim = [T('An exact run time is not shown because pump flow information is not available.', 'مدة التشغيل الدقيقة غير معروضة لأن معلومات تدفق المضخة غير متوفرة.')];
      if (!IR.estimate) lim.unshift(T('No calculated irrigation estimate is available yet.', 'ما في تقدير ري محسوب لحد الآن.'));
      if (unconfirmed > 0) lim.push(T('Unconfirmed irrigation records are not counted.', 'سجلات الري غير المؤكدة ما بتنحسب.'));
      if (!WX || !WX.days || !WX.days.length) lim.push(T('Weather data is missing, so rain was not considered.', 'بيانات الطقس ناقصة، فما انحسب المطر.'));
      if (!P || !P.irrigation_method) lim.push(T('The irrigation method is not set.', 'طريقة الري غير محددة.'));
      make('irrigation', {
        summary: confirmed[0]
          ? T('The last confirmed irrigation was on {last_irrigation}.' + (e.some((x) => x.key === 'irrigation_method') ? ' Method: {irrigation_method}.' : ''),
              'آخر ري مؤكد كان بتاريخ {last_irrigation}.' + (e.some((x) => x.key === 'irrigation_method') ? ' طريقة الري: {irrigation_method}.' : ''))
          : T('No confirmed irrigation is recorded for this farm yet.', 'ما في ري مؤكد مسجل لهذه المزرعة لحد الآن.'),
        action: IR.estimate
          ? T('Compare the calculated irrigation estimate ({irrigation_estimate}) with what you see in the field before you irrigate.', 'قارن تقدير الري المحسوب ({irrigation_estimate}) مع وضع الأرض قبل ما تروي.')
          : confirmed[0]
            ? T('Check the soil moisture in the field, and record your next irrigation after you do it.', 'افحص رطوبة التربة بالأرض، وسجّل الري الجاي بعد ما تنفذه.')
            : T('Record every irrigation you do, so the system can support an estimate later.', 'سجّل كل ري تعمله، حتى يقدر النظام يساعدك بتقدير لاحقاً.'),
        why: rainDays
          ? T('The forecast shows rain on {forecast_rain_days} day(s), which may reduce the need to irrigate.', 'التوقعات فيها مطر. عدد الأيام المتوقع فيها مطر: {forecast_rain_days}. وهذا ممكن يقلل حاجتك للري.')
          : IR.estimate
            ? T('The system has calculated an estimate that can help you decide.', 'في تقدير محسوب من النظام بيساعدك تقرر.')
            : T('Recording irrigation gives the system the information it needs to guide you.', 'تسجيل الري بيعطي النظام المعلومات اللازمة لإرشادك.'),
        limitations: lim, evidence: e
      });
    }

    /* ---- Fertilizer ---- */
    const doseLim = T('No fertilizer dose is shown. A dose needs soil information and a reviewed recommendation.', 'ما في جرعة سماد معروضة. الجرعة بدها معلومات عن التربة وتوصية مراجَعة.');
    if (!FN) {
      make('fertilizer', {
        summary: T('Financial data could not be loaded, so the fertilizer budget is unknown.', 'ما قدرنا نحمّل البيانات المالية، فميزانية الأسمدة غير معروفة.'),
        action: T('Refresh the data, then review your fertilizer plan.', 'جرّب تحديث البيانات، وبعدها راجع خطة التسميد.'),
        why: T('The fertilizer budget comes from the financial results.', 'ميزانية الأسمدة بتيجي من النتائج المالية.'),
        limitations: [doseLim]
      });
    } else if (FN.fertilizer_budget_jod != null) {
      const e = []; ev(e, 'fertilizer_budget_jod', FN.fertilizer_budget_jod, 'jod'); ev(e, 'crop_stage', P && P.crop_stage, 'stage');
      const lim = [doseLim]; if (!P || !P.crop_stage) lim.push(T('The crop stage is not set.', 'مرحلة المحصول غير محددة.'));
      make('fertilizer', {
        summary: T('A fertilizer budget of {fertilizer_budget_jod} is calculated for this farm.' + (P && P.crop_stage ? ' Crop stage: {crop_stage}.' : ''),
          'ميزانية الأسمدة المحسوبة لهذه المزرعة هي {fertilizer_budget_jod}.' + (P && P.crop_stage ? ' مرحلة المحصول: {crop_stage}.' : '')),
        action: T('Review the fertilizer plan and its budget with your agricultural advisor before you buy.', 'راجع خطة التسميد وميزانيتها مع مرشدك الزراعي قبل الشراء.'),
        why: T('The budget comes from the system calculation, so it helps you plan costs ahead.', 'الميزانية ناتجة عن حساب النظام، وبتساعدك تخطط التكلفة مسبقاً.'),
        limitations: lim, evidence: e
      });
    } else {
      make('fertilizer', {
        summary: T('There is no fertilizer budget for this farm yet.', 'ما في ميزانية أسمدة لهذه المزرعة لحد الآن.'),
        action: T('Add the fertilizer plan inputs so a budget can be calculated.', 'أضف مدخلات خطة التسميد حتى تنحسب الميزانية.'),
        why: T('Without a plan the system cannot estimate fertilizer costs.', 'بدون خطة، ما بقدر النظام يقدّر تكلفة الأسمدة.'),
        limitations: [doseLim]
      });
    }

    /* ---- Inspection ---- */
    const inspLim = [T('Reminders are not confirmed diagnoses of any disease.', 'التذكيرات مش تشخيص مؤكد لأي مرض.'), T('The system does not detect disease from photos.', 'النظام ما بكشف الأمراض من الصور.')];
    if (IN) {
      const n = IN.reminders.length, e = [];
      ev(e, 'reminder_count', n, 'count');
      if (n) ev(e, 'next_reminder', IN.reminders[0].title, 'text');
      make('inspection', n ? {
        summary: T('There are {reminder_count} inspection reminder(s) for this farm.', 'عدد تذكيرات الفحص لهذه المزرعة: {reminder_count}.'),
        action: T('Inspect your plants in the field, starting with: {next_reminder}.', 'افحص نباتاتك بالأرض. التذكير الأول: {next_reminder}.'),
        why: T('Reminders help you notice problems early.', 'التذكيرات بتساعدك تلاحظ المشاكل بدري.'),
        limitations: inspLim, evidence: e
      } : {
        summary: T('There are no inspection reminders right now.', 'ما في تذكيرات فحص حالياً.'),
        action: T('Keep up your regular field walks and note anything unusual.', 'كمّل جولاتك المنتظمة بالأرض ودوّن أي شي غير عادي.'),
        why: T('Regular inspection is the main way to spot problems early.', 'الفحص المنتظم هو أهم طريقة لاكتشاف المشاكل بدري.'),
        limitations: inspLim, evidence: e
      });
    }

    /* ---- Finance ---- */
    if (FN) {
      const e = [];
      ev(e, 'recorded_costs_jod', FN.recorded_costs_jod, 'jod'); ev(e, 'projected_costs_jod', FN.projected_costs_jod, 'jod');
      ev(e, 'actual_revenue_jod', FN.actual_revenue_jod, 'jod'); ev(e, 'projected_revenue_jod', FN.projected_revenue_jod, 'jod');
      const lim = [T('No market prices are used.', 'ما بنستخدم أسعار السوق.')];
      if (FN.projected_costs_jod != null || FN.projected_revenue_jod != null) lim.unshift(T('Projected costs and revenue are estimates, not results.', 'التكاليف والإيراد المتوقعة تقديرات وليست نتائج.'));
      if (FN.recorded_costs_jod != null) {
        make('finance', {
          summary: T('Recorded costs are {recorded_costs_jod}' + (FN.actual_revenue_jod != null ? ' and recorded revenue is {actual_revenue_jod}.' : '.'),
            'التكاليف المسجلة {recorded_costs_jod}' + (FN.actual_revenue_jod != null ? ' والإيراد المسجل {actual_revenue_jod}.' : '.')),
          action: T('Keep recording every cost and sale, and compare the recorded numbers with the projections.', 'استمر بتسجيل كل تكلفة وكل بيعة، وقارن المسجل مع المتوقع.'),
          why: T('Recorded figures are actual; projected figures are estimates and can change.', 'الأرقام المسجلة فعلية، أما المتوقعة فهي تقديرات وممكن تتغير.'),
          limitations: lim, evidence: e
        });
      } else {
        make('finance', {
          summary: T('There are no recorded costs for this farm yet.', 'ما في تكاليف مسجلة لهذه المزرعة لحد الآن.'),
          action: T('Start recording your costs so the financial summary can appear.', 'ابدأ بتسجيل التكاليف حتى يظهر الملخص المالي.'),
          why: T('Only recorded costs show your real spending.', 'التكاليف المسجلة بس هي اللي بتبيّن مصروفك الحقيقي.'),
          limitations: lim, evidence: e
        });
      }
    }

    /* ---- Missing farm details ---- */
    if (P) {
      const names = [];
      if (P.area_dunum == null) names.push(['area', 'المساحة']);
      if (!P.planting_date) names.push(['planting date', 'تاريخ الزراعة']);
      if (!P.crop_stage) names.push(['crop stage', 'مرحلة المحصول']);
      if (!P.irrigation_method) names.push(['irrigation method', 'طريقة الري']);
      if (!P.location) names.push(['location', 'الموقع']);
      if (names.length) {
        make('data', {
          summary: T('Some farm details are missing: {missing_fields}.', 'بعض تفاصيل المزرعة ناقصة: {missing_fields}.'),
          action: T('Complete the farm profile.', 'أكمل بيانات المزرعة.'),
          why: T('Complete details let the recommendations be more specific to your farm.', 'التفاصيل الكاملة بتخلي التوصيات أدق لمزرعتك.'),
          limitations: [T('Recommendations may stay general until these details are filled in.', 'التوصيات ممكن تضل عامة لحد ما تنعبّى هالبيانات.')],
          evidence: [{ key: 'missing_fields', unit: 'text', value: T(names.map((n) => n[0]).join(', '), names.map((n) => n[1]).join('، ')) }]
        });
      }
    }
    return recs;
  };
})();
