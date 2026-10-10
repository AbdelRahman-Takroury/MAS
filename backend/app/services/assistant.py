"""Bounded Groq assistant with deterministic bilingual fallback."""

import json
import re
from typing import Any

from groq import Groq
from sqlalchemy.orm import Session

from ..config import settings
from ..schemas.assistant import AssistantRequest, AssistantResponse
from ..schemas.dashboard import DashboardResponse
from ..schemas.knowledge import RetrievedPassage
from .dashboard import build_dashboard
from .retrieval import retrieve_passages


GROQ_TIMEOUT_SECONDS = 5.0
_NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _document_references(passages: list[RetrievedPassage]) -> list[dict]:
    return [
        {
            "document_id": passage.id,
            "title": passage.title,
            "section": passage.section,
            "source_url": passage.source_url,
        }
        for passage in passages
    ]


def _calculator_references(dashboard: DashboardResponse) -> list[dict]:
    result_id = dashboard.generated_at.isoformat()
    return [
        {
            "calculator": dashboard.irrigation.calculator_version,
            "result_id": result_id,
        },
        {"calculator": "water-budget-v1", "result_id": result_id},
        {"calculator": dashboard.finance.calculator_version, "result_id": result_id},
    ]


def _limitations(language: str, dashboard: DashboardResponse) -> list[str]:
    if language == "ar":
        values = [
            "هذه النتائج أداة دعم قرار وليست ضمانا زراعيا أو ماليا.",
            "مؤشرات الفحص البيئي لا تشخص إصابة ولا تصف علاجا بالمبيدات.",
            "لم تتم نمذجة خسارة المحصول بسبب عجز المياه.",
        ]
        if dashboard.irrigation.runtime_hours is None:
            values.append("مدة الري غير متاحة عندما يكون تدفق النظام غير معروف.")
        return values
    values = [
        "These results are decision support, not an agronomic or financial guarantee.",
        "Environmental inspection indicators do not diagnose infection or prescribe pesticides.",
        "No crop-yield loss from water shortage was modeled.",
    ]
    if dashboard.irrigation.runtime_hours is None:
        values.append("Irrigation runtime is unavailable while system flow is unknown.")
    return values


def _fallback_answer(
    language: str,
    dashboard: DashboardResponse,
    passages: list[RetrievedPassage],
) -> str:
    source = passages[0].title if passages else ("المصدر غير متاح" if language == "ar" else "Source unavailable")
    top_id = passages[0].id if passages else ""
    if top_id.startswith("financial-"):
        finance = dashboard.finance
        if language == "ar":
            if finance.break_even_jod_per_kg is None:
                result = "سعر التعادل غير متاح لأن كمية المحصول القابل للتسويق صفر أو غير معروفة."
            else:
                result = (
                    f"التكلفة الكلية المتوقعة هي {finance.projected_total_cost_jod:g} دينار، "
                    f"وسعر التعادل التقديري هو {finance.break_even_jod_per_kg:g} دينار لكل كغم."
                )
            return f"{result} المصدر: {source}. هذه نتيجة تقديرية وليست ضمانا للربح."
        if finance.break_even_jod_per_kg is None:
            result = "Break-even price is unavailable because marketable quantity is zero or unknown."
        else:
            result = (
                f"Projected total cost is {finance.projected_total_cost_jod:g} JOD and the estimated "
                f"break-even price is {finance.break_even_jod_per_kg:g} JOD per kg."
            )
        return f"{result} Source: {source}. This estimate does not guarantee profit."

    if top_id.startswith("tomato-"):
        assessment = dashboard.inspection.assessment
        if language == "ar":
            assessment_ar = {
                "favorable": "توجد ظروف تستدعي الفحص",
                "not_favorable": "لم تُفعّل قاعدة فحص",
                "cannot_assess": "تعذر التقييم بسبب نقص البيانات",
            }[assessment]
            return (
                f"حالة الفحص البيئي الحالية: {assessment_ar}. افحص الأوراق والسيقان والثمار ميدانيا "
                f"وسجل الأعراض، ولا تعتبر المظهر أو الطقس تشخيصا. المصدر: {source}."
            )
        return (
            f"The current environmental inspection state is {assessment}. Inspect leaves, stems, and "
            f"fruit and record symptoms; appearance and weather are not a diagnosis. Source: {source}."
        )

    budget = dashboard.water_budget
    if language == "ar":
        if budget.water_required_liters is None:
            result = "لا يمكن حساب الاحتياج أو عجز المياه لأن بيانات الطلب غير مكتملة."
        else:
            result = (
                f"الاحتياج التقديري هو {budget.water_required_liters:g} لتر، والمياه المتاحة "
                f"{budget.water_available_liters:g} لتر، والعجز التقديري "
                f"{(budget.water_shortage_liters or 0):g} لتر."
            )
        return f"{result} المصدر: {source}. لم يتم استنتاج انخفاض في المحصول من هذا العجز."
    if budget.water_required_liters is None:
        result = "Water requirement and shortage cannot be calculated because demand data is incomplete."
    else:
        result = (
            f"Estimated demand is {budget.water_required_liters:g} liters, available water is "
            f"{budget.water_available_liters:g} liters, and estimated shortage is "
            f"{(budget.water_shortage_liters or 0):g} liters."
        )
    return f"{result} Source: {source}. No yield reduction was inferred from this shortage."


def _numeric_values(value: Any) -> set[str]:
    numbers: set[str] = set()
    if isinstance(value, bool) or value is None:
        return numbers
    if isinstance(value, (int, float)):
        numbers.add(f"{value:g}")
    elif isinstance(value, dict):
        for item in value.values():
            numbers.update(_numeric_values(item))
    elif isinstance(value, list):
        for item in value:
            numbers.update(_numeric_values(item))
    return numbers


def _numbers_are_grounded(answer: str, dashboard: DashboardResponse) -> bool:
    allowed = _numeric_values(dashboard.model_dump(mode="json"))
    for match in _NUMBER_PATTERN.findall(answer):
        normalized = match.replace(",", "")
        try:
            normalized = f"{float(normalized):g}"
        except ValueError:
            return False
        if normalized not in allowed:
            return False
    return True


def _prompt_context(
    request: AssistantRequest,
    dashboard: DashboardResponse,
    passages: list[RetrievedPassage],
) -> list[dict[str, str]]:
    language_name = "Arabic" if request.language == "ar" else "English"
    system = (
        f"Respond only in {language_name}. Explain only the supplied calculator results and reviewed "
        "passages. Repeat numeric values only when they appear in CALCULATOR_RESULTS. Never diagnose "
        "infection, prescribe pesticide treatment, perform a database write, or infer yield loss from "
        "water shortage. Explicitly state relevant limitations. Cite at least one retrieved source by "
        "its exact title. Keep the answer concise."
    )
    context = {
        "CALCULATOR_RESULTS": dashboard.model_dump(mode="json"),
        "RETRIEVED_PASSAGES": [passage.model_dump(mode="json") for passage in passages],
        "QUESTION": request.question,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]


def _groq_answer(
    request: AssistantRequest,
    dashboard: DashboardResponse,
    passages: list[RetrievedPassage],
) -> str:
    client = Groq(
        api_key=settings.groq_api_key,
        timeout=GROQ_TIMEOUT_SECONDS,
        max_retries=0,
    )
    completion = client.chat.completions.create(
        model=settings.groq_model,
        messages=_prompt_context(request, dashboard, passages),
        temperature=0.1,
        max_completion_tokens=500,
    )
    answer = completion.choices[0].message.content
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Groq returned an empty answer")
    if not _numbers_are_grounded(answer, dashboard):
        raise ValueError("Groq answer introduced an unsupported numeric value")
    if passages and not any(passage.title in answer for passage in passages):
        raise ValueError("Groq answer omitted the retrieved source title")
    return answer.strip()


def answer_question(
    database: Session,
    request: AssistantRequest,
) -> AssistantResponse:
    """Retrieve current results and citations, then use Groq or a safe fallback."""
    dashboard = build_dashboard(database, request.farm_id)
    passages = retrieve_passages(request.question, request.language, limit=3)
    used_fallback = not bool(settings.groq_api_key)
    answer = ""
    if not used_fallback:
        try:
            answer = _groq_answer(request, dashboard, passages)
        except Exception:
            used_fallback = True
    if used_fallback:
        answer = _fallback_answer(request.language, dashboard, passages)

    return AssistantResponse.model_validate(
        {
            "answer": answer,
            "language": request.language,
            "used_fallback": used_fallback,
            "calculator_references": _calculator_references(dashboard),
            "document_references": _document_references(passages),
            "limitations": _limitations(request.language, dashboard),
        }
    )
