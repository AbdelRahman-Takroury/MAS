"""Deterministic, farm-specific advisory cards built from read-only dashboard facts."""

from decimal import Decimal

from ..schemas.dashboard import DashboardResponse
from ..models import CropSeason


def _text(en: str, ar: str) -> dict[str, str]:
    return {"en": en, "ar": ar}


def _evidence(key: str, en: str, ar: str, value, unit: str | None = None) -> dict:
    item = {"key": key, "label": _text(en, ar), "value": value}
    if unit:
        item["unit"] = unit
    return item


def _source(en: str, ar: str, url: str | None = None) -> dict:
    return {"title": _text(en, ar), "url": url}


_WEATHER_FIELDS = {
    "temperature_max_c": _text("maximum temperature", "الحرارة العظمى"),
    "temperature_min_c": _text("minimum temperature", "الحرارة الصغرى"),
    "precipitation_mm": _text("rainfall", "الهطول"),
    "relative_humidity_mean_percent": _text("mean relative humidity", "متوسط الرطوبة النسبية"),
    "et0_mm": _text("reference evapotranspiration", "البخر النتح المرجعي"),
}


def _card(suffix: str, topic: str, summary: dict, action: dict, why: dict,
          evidence: list[dict], limitations: list[dict], sources: list[dict]) -> dict:
    return {
        "id": suffix, "topic": topic, "summary": summary, "action": action, "why": why,
        "evidence": evidence, "limitations": limitations, "sources": sources,
    }


def build_recommendations(dashboard: DashboardResponse, season: CropSeason) -> list[dict]:
    """Only facts in the current calculation or active-season records can drive cards."""
    candidates = []
    weather = dashboard.weather
    irrigation = dashboard.irrigation
    budget = dashboard.water_budget
    finance = dashboard.finance
    inspection = dashboard.inspection

    weather_source = (
        [_source("Open-Meteo forecast", "تنبؤ Open-Meteo", weather.source.reference)]
        if weather.data_kind in {"live", "cached"} and weather.source and weather.source.reference else []
    )
    irrigation_source = (
        [_source("FAO-56 irrigation estimate", "تقدير الري FAO-56", irrigation.source.reference)]
        if irrigation.source and irrigation.source.reference else []
    )
    if weather.coverage_status != "complete" or weather.data_kind == "cached":
        coverage = weather.coverage
        missing_fields = sorted({entry.split(":")[-1] for entry in weather.missing_inputs})
        if weather.coverage_status == "unavailable":
            summary = _text("No usable forecast is available for this farm.", "لا يتوفر تنبؤ طقس صالح لهذه المزرعة.")
            action = _text("Check forecast availability and field conditions before relying on the irrigation estimate.",
                           "تحقق من توفر التنبؤ وظروف الحقل قبل الاعتماد على تقدير الري.")
        elif weather.coverage_status == "partial":
            summary = _text("This farm's forecast has incomplete coverage.", "تغطية تنبؤ هذه المزرعة غير مكتملة.")
            action = _text("Refresh the forecast and verify the missing weather fields before using the estimate.",
                           "حدّث التنبؤ وتحقق من حقول الطقس الناقصة قبل استخدام التقدير.")
        else:
            summary = _text("This farm is using a cached forecast.", "تستخدم هذه المزرعة تنبؤاً مخزناً.")
            action = _text("Check the forecast retrieval time and refresh it before a time-sensitive decision.",
                           "تحقق من وقت جلب التنبؤ وحدّثه قبل اتخاذ قرار يعتمد على الوقت.")
        evidence = [
            _evidence("weather_coverage", "Forecast coverage", "تغطية التنبؤ",
                      {"complete": _text("complete", "مكتملة"), "partial": _text("partial", "جزئية"),
                       "unavailable": _text("unavailable", "غير متاحة")}[weather.coverage_status], "text"),
            _evidence("weather_origin", "Forecast origin", "مصدر بيانات التنبؤ",
                      {"live": _text("live", "مباشر"), "cached": _text("cached", "مخزن"),
                       None: _text("unavailable", "غير متاح")}[weather.data_kind], "text"),
            _evidence("complete_forecast_days", "Complete forecast days", "أيام التنبؤ المكتملة", coverage.get("complete_days", 0), "count"),
            _evidence("requested_forecast_days", "Requested forecast days", "أيام التنبؤ المطلوبة", coverage.get("requested_days", 0), "count"),
        ]
        if missing_fields:
            evidence.append(_evidence("missing_weather_fields", "Missing weather fields", "حقول الطقس الناقصة",
                                      _text(", ".join(_WEATHER_FIELDS.get(field, _text(field, field))["en"] for field in missing_fields),
                                            "، ".join(_WEATHER_FIELDS.get(field, _text(field, field))["ar"] for field in missing_fields)), "text"))
        if weather.forecast_generated_at:
            evidence.append(_evidence("forecast_retrieved_at", "Forecast retrieved at", "وقت جلب التنبؤ",
                                      weather.forecast_generated_at.isoformat(), "text"))
        candidates.append(_card("weather", "data", summary, action,
                                _text("Incomplete or older weather limits the confidence of time-specific calculations.",
                                      "نقص بيانات الطقس أو قدمها يحد من الاعتماد على الحسابات المرتبطة بالوقت."),
                                evidence,
                                [_text("Forecast data does not measure soil moisture or diagnose crop health.",
                                       "بيانات التنبؤ لا تقيس رطوبة التربة ولا تشخص صحة المحصول.")],
                                weather_source))

    if budget.water_available_liters is None:
        saved = budget.allocation_liters
        if not budget.forecast_period_start or not budget.forecast_period_end:
            reason = _text("The forecast period is unavailable, so water availability cannot be matched to it.",
                           "فترة التنبؤ غير متاحة، لذلك لا يمكن مطابقة المياه المتاحة معها.")
            action = _text("Restore the current forecast, then confirm the available water amount and its dates.",
                           "استعد التنبؤ الحالي ثم تحقق من كمية المياه المتاحة وتواريخها.")
        elif saved is not None:
            reason = _text("The saved allocation does not match the current forecast period.",
                           "فترة المياه المحفوظة لا تطابق فترة التنبؤ الحالية.")
            action = _text("Update the available water amount with dates matching the forecast period.",
                           "حدّث كمية المياه المتاحة مع تاريخي بداية ونهاية يطابقان فترة التنبؤ.")
        else:
            reason = _text("No period-matched available-water amount is recorded.",
                           "لا توجد كمية مياه متاحة مسجلة للفترة المطابقة.")
            action = _text("Record the available water amount with dates matching the forecast period.",
                           "سجل كمية المياه المتاحة مع تاريخي بداية ونهاية يطابقان فترة التنبؤ.")
        evidence = [
            _evidence("water_availability", "Available water for forecast", "المياه المتاحة لفترة التنبؤ",
                      _text("unknown", "غير معروفة"), "text"),
        ]
        if budget.water_required_liters is not None:
            evidence.append(_evidence("water_demand", "Estimated water demand", "الاحتياج المائي التقديري",
                                      budget.water_required_liters, "L"))
        if saved is not None:
            label = (_text("Saved seeded-demo allocation", "كمية المياه التجريبية المحفوظة")
                     if budget.availability_source == "seeded_demo" else
                     _text("Saved allocation", "كمية المياه المحفوظة"))
            evidence.append(_evidence("saved_allocation", label["en"], label["ar"], saved, "L"))
            evidence.append(_evidence("saved_water_period", "Saved allocation period", "فترة المياه المحفوظة",
                                      f"{budget.water_period_start} – {budget.water_period_end}", "text"))
        if budget.forecast_period_start and budget.forecast_period_end:
            evidence.append(_evidence("forecast_period", "Forecast period", "فترة التنبؤ",
                                      f"{budget.forecast_period_start} – {budget.forecast_period_end}", "text"))
        candidates.append(_card("water", "irrigation",
                                _text("Water shortage cannot be calculated for this farm.", "لا يمكن حساب عجز المياه لهذه المزرعة."),
                                action,
                                reason, evidence,
                                [_text("Unknown availability is missing data, not zero; no shortage or yield loss can be inferred.",
                                       "المياه غير المعروفة بيانات ناقصة وليست صفراً؛ لا يمكن استنتاج عجز أو خسارة محصول."),
                                 *([_text("The saved amount is a seeded demo value, not measured farm availability.",
                                          "الكمية المحفوظة قيمة تجريبية وليست قياساً لمياه المزرعة.")]
                                   if saved is not None and budget.availability_source == "seeded_demo" else [])],
                                irrigation_source))
    elif budget.availability_source == "seeded_demo":
        candidates.append(_card("demo_water", "irrigation",
                                _text("The available-water figure is seeded demonstration data.",
                                      "رقم المياه المتاحة مأخوذ من بيانات تجريبية."),
                                _text("Replace the demo allocation with this farm's known amount and matching period before planning.",
                                      "استبدل كمية المياه التجريبية بقيمة هذه المزرعة وفترتها المطابقة قبل التخطيط."),
                                _text("The saved amount is illustrative, not a measured supply.",
                                      "الكمية المحفوظة توضيحية وليست قياساً للمياه المتوفرة."),
                                [_evidence("seeded_allocation", "Seeded demo allocation", "كمية المياه التجريبية",
                                           budget.water_available_liters, "L")],
                                [_text("Any shortage calculated with a seeded demo amount is illustrative only.",
                                       "أي عجز محسوب باستخدام كمية تجريبية هو توضيحي فقط.")],
                                irrigation_source))
    elif budget.water_status == "shortage":
        candidates.append(_card("water", "irrigation",
                                _text("The entered water is below the estimated demand for the matching period.",
                                      "المياه المدخلة أقل من الاحتياج التقديري للفترة المطابقة."),
                                _text("Check the saved allocation and field conditions, then review the period's irrigation plan with a local advisor.",
                                      "تحقق من كمية المياه وظروف الحقل ثم راجع خطة الري للفترة مع مرشد محلي."),
                                _text("The calculator compares available liters with estimated required liters for the same period.",
                                      "الحاسبة تقارن لترات المياه المتاحة بالاحتياج التقديري للفترة نفسها."),
                                [
                                    _evidence("water_demand", "Estimated demand", "الاحتياج التقديري", budget.water_required_liters, "L"),
                                    _evidence("available_water", "Available water", "المياه المتاحة", budget.water_available_liters, "L"),
                                    _evidence("water_shortage", "Estimated shortage", "العجز التقديري", budget.water_shortage_liters, "L"),
                                ],
                                [_text("This is a planning comparison, not a soil-moisture measurement or yield-loss prediction.",
                                       "هذه مقارنة للتخطيط وليست قياساً لرطوبة التربة أو توقعاً لخسارة المحصول.")],
                                irrigation_source))

    if "system_flow_liters_per_hour" in irrigation.missing_inputs:
        evidence = [_evidence("system_flow", "System flow", "تدفق نظام الري",
                              _text("unknown", "غير معروف"), "text")]
        if irrigation.water_required_liters is not None:
            evidence.append(_evidence("irrigation_demand", "Estimated irrigation requirement", "احتياج الري التقديري",
                                      irrigation.water_required_liters, "L"))
        candidates.append(_card("flow", "irrigation",
                                _text("Irrigation runtime is unavailable for this farm.", "مدة الري غير متاحة لهذه المزرعة."),
                                _text("Measure or confirm system flow before using a runtime estimate.",
                                      "قس أو تحقق من تدفق نظام الري قبل استخدام تقدير مدة الري."),
                                _text("The calculator needs flow in liters per hour to convert water volume into runtime.",
                                      "تحتاج الحاسبة إلى التدفق باللترات لكل ساعة لتحويل حجم المياه إلى مدة تشغيل."),
                                evidence,
                                [_text("Estimated water need is not an irrigation schedule.",
                                       "الاحتياج المائي التقديري ليس جدول ري جاهزاً.")],
                                irrigation_source))

    if finance.missing_inputs or finance.break_even_jod_per_kg is None:
        names = {
            "expected_marketable_kg": _text("expected remaining marketable harvest", "المحصول المتبقي المتوقع القابل للتسويق"),
            "sale_price_jod_per_kg": _text("assumed selling price per kilogram", "سعر البيع المفترض لكل كيلوغرام"),
        }
        missing_en = ", ".join(names[key]["en"] for key in finance.missing_inputs if key in names)
        missing_ar = "، ".join(names[key]["ar"] for key in finance.missing_inputs if key in names)
        if not missing_en:
            missing_en = "a positive remaining marketable harvest estimate"
            missing_ar = "تقديراً موجباً للمحصول المتبقي القابل للتسويق"
        candidates.append(_card("finance", "finance",
                                _text("This farm's break-even estimate is unavailable or incomplete.",
                                      "تقدير سعر التعادل لهذه المزرعة غير متاح أو غير مكتمل."),
                                _text(f"Enter the known {missing_en} for this season.",
                                      f"أدخل {missing_ar} المعروف لهذا الموسم."),
                                _text("Without those inputs, revenue, profit, or break-even can be unavailable or incomplete.",
                                      "من دون هذه المدخلات قد يتعذر حساب الإيراد أو الربح أو سعر التعادل بشكل مكتمل."),
                                [
                                    _evidence("missing_financial_inputs", "Missing finance inputs", "المدخلات المالية الناقصة",
                                              _text(missing_en, missing_ar), "text"),
                                    _evidence("projected_total_cost", "Projected total cost", "التكلفة الكلية المتوقعة",
                                              finance.projected_total_cost_jod, "jod"),
                                    _evidence("expense_records", "Recorded expense entries", "سجلات المصروفات",
                                              len(season.expenses), "count"),
                                ],
                                [_text("Projected values depend on complete and accurate recorded costs and assumptions.",
                                       "القيم المتوقعة تعتمد على اكتمال التكاليف المسجلة والافتراضات ودقتها.")],
                                [_source("Farm finance calculator", "حاسبة مالية المزرعة")]))
    else:
        candidates.append(_card("finance", "finance",
                                _text("The season has a calculated break-even estimate.", "للموسم تقدير محسوب لسعر التعادل."),
                                _text("Compare the assumed selling price and remaining marketable harvest with current farm records.",
                                      "قارن سعر البيع المفترض والمحصول المتبقي القابل للتسويق بسجلات المزرعة الحالية."),
                                _text("The estimate uses recorded costs and actual sales alongside the entered assumptions.",
                                      "يعتمد التقدير على التكاليف والمبيعات المسجلة إلى جانب الافتراضات المدخلة."),
                                [
                                    _evidence("break_even", "Estimated break-even price", "سعر التعادل التقديري",
                                              finance.break_even_jod_per_kg if finance.break_even_jod_per_kg is not None else _text("unavailable", "غير متاح"),
                                              "jod/kg" if finance.break_even_jod_per_kg is not None else "text"),
                                    _evidence("assumed_price", "Assumed selling price", "سعر البيع المفترض",
                                              finance.assumed_sale_price_jod_per_kg, "jod/kg"),
                                    _evidence("expense_records", "Recorded expense entries", "سجلات المصروفات",
                                              len(season.expenses), "count"),
                                    _evidence("sale_records", "Recorded sale entries", "سجلات المبيعات",
                                              len(season.sales), "count"),
                                ],
                                [_text("Break-even is a scenario estimate, not a guaranteed selling price or profit.",
                                       "سعر التعادل تقدير لسيناريو وليس ضماناً لسعر البيع أو الربح.")],
                                [_source("Farm finance calculator", "حاسبة مالية المزرعة")]))

    if season.expenses or season.sales or season.harvests or season.irrigation_events:
        total_expenses = sum((entry.amount_jod for entry in season.expenses), Decimal("0"))
        candidates.append(_card("records", "data",
                                _text("This season has recorded farm activity.", "توجد أنشطة مسجلة لهذا الموسم."),
                                _text("Reconcile the recorded expenses, sales, harvests, and irrigation events with field notes and receipts.",
                                      "طابق سجلات المصروفات والمبيعات والحصاد والري مع ملاحظات الحقل والإيصالات."),
                                _text("Recorded entries feed the season history; expense and sale entries also affect financial calculations.",
                                      "تُكوّن السجلات تاريخ الموسم؛ وتؤثر المصروفات والمبيعات المسجلة في الحسابات المالية."),
                                [
                                    _evidence("expense_records", "Expense entries", "سجلات المصروفات", len(season.expenses), "count"),
                                    _evidence("recorded_expenses", "Recorded expense amount", "قيمة المصروفات المسجلة", float(total_expenses), "jod"),
                                    _evidence("sale_records", "Sale entries", "سجلات المبيعات", len(season.sales), "count"),
                                    _evidence("harvest_records", "Harvest entries", "سجلات الحصاد", len(season.harvests), "count"),
                                    _evidence("irrigation_records", "Irrigation entries", "سجلات الري", len(season.irrigation_events), "count"),
                                ],
                                [_text("Record counts do not establish crop condition or future yield.",
                                       "عدد السجلات لا يثبت حالة المحصول أو إنتاجه المستقبلي.")],
                                [_source("Active-season farm records", "سجلات موسم المزرعة النشط")]))

    if inspection.assessment in {"favorable", "cannot_assess"}:
        candidates.append(_card("inspection", "inspection",
                                _text("Environmental inspection needs field confirmation.",
                                      "يلزم التحقق الحقلي من مؤشرات الفحص البيئي."),
                                _text("Inspect tomato leaves, stems, and fruit; record the place and date of any symptoms.",
                                      "افحص أوراق البندورة وسيقانها وثمارها وسجل مكان أي أعراض وتاريخها."),
                                _text(
                                    "The forecast-based inspection rule produced an alert."
                                    if inspection.assessment == "favorable" else
                                    "Required weather evidence is incomplete, so inspection conditions cannot be assessed.",
                                    "أظهرت قاعدة الفحص المعتمدة على التنبؤ تنبيهاً."
                                    if inspection.assessment == "favorable" else
                                    "بيانات الطقس المطلوبة غير مكتملة، لذلك تعذر تقييم ظروف الفحص.",
                                ),
                                [
                                    _evidence("inspection_state", "Inspection state", "حالة الفحص",
                                              {"favorable": _text("inspection alert", "تنبيه للفحص"),
                                               "cannot_assess": _text("cannot assess", "تعذر التقييم")}[inspection.assessment], "text"),
                                    _evidence("inspection_alerts", "Inspection alerts", "تنبيهات الفحص", len(inspection.alerts), "count"),
                                ],
                                [_text("Weather and appearance alone do not diagnose infection or determine pesticide treatment.",
                                       "الطقس والمظهر وحدهما لا يشخصان الإصابة ولا يحددان علاجاً بالمبيدات.")],
                                [_source("UC IPM tomato field inspection", "إرشادات UC IPM لفحص البندورة",
                                         "https://ipm.ucanr.edu/agriculture/tomato/")]))

    # Preserve the existing voice/UI identifier while making its content farm-specific.
    candidates[0]["id"] = dashboard.farm_id + "-review"
    for candidate in candidates[1:]:
        candidate["id"] = dashboard.farm_id + "-" + candidate["id"]
    return candidates

