"""Read-only assistant with reviewed retrieval and validated Groq selection."""

import json
import re
from typing import Literal

from groq import Groq
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..config import settings
from ..schemas.assistant import AssistantRequest, AssistantResponse
from ..schemas.common import StrictModel
from ..schemas.dashboard import DashboardResponse
from ..schemas.knowledge import RetrievedPassage
from .dashboard import build_dashboard
from .retrieval import retrieve_passages


GROQ_TIMEOUT_SECONDS = 5.0
_NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")


class _ProviderSelection(StrictModel):
    """The provider selects evidence; it cannot supply answer text or new facts."""

    language: Literal["ar", "en"]
    topic: Literal["water", "finance", "inspection"]
    source_id: str


def _topic(passage: RetrievedPassage) -> str:
    if passage.id.startswith("financial-"):
        return "finance"
    if passage.id.startswith("tomato-"):
        return "inspection"
    return "water"


def _relevant_passages(passages: list[RetrievedPassage], language: str) -> list[RetrievedPassage]:
    matched = [passage for passage in passages if passage.score > 0]
    if not matched:
        return []
    top_topic = _topic(matched[0])
    related = [passage for passage in matched if _topic(passage) == top_topic]
    same_language = [passage for passage in related if passage.language == language]
    return same_language or related


def _document_references(passages: list[RetrievedPassage]) -> list[dict]:
    return [
        {"document_id": p.id, "title": p.title, "section": p.section, "source_url": p.source_url}
        for p in passages
    ]


def _calculator_references(dashboard: DashboardResponse) -> list[dict]:
    result_id = dashboard.generated_at.isoformat()
    return [
        {"calculator": dashboard.irrigation.calculator_version, "result_id": result_id},
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


def _metric_claims(language: str, dashboard: DashboardResponse) -> dict[str, str]:
    """Bind each displayed number to its own metric and unit."""
    finance = dashboard.finance
    budget = dashboard.water_budget
    if language == "ar":
        financial = (
            "سعر التعادل غير متاح لأن كمية المحصول القابل للتسويق صفر أو غير معروفة."
            if finance.break_even_jod_per_kg is None else
            f"التكلفة الكلية المتوقعة هي {finance.projected_total_cost_jod:g} دينار، "
            f"وسعر التعادل التقديري هو {finance.break_even_jod_per_kg:g} دينار لكل كغم."
        )
        water = (
            "لا يمكن حساب عجز المياه لأن بيانات الطلب أو المياه المتاحة للفترة غير مكتملة."
            if any(value is None for value in (budget.water_required_liters, budget.water_available_liters, budget.water_shortage_liters)) else
            f"الاحتياج التقديري هو {budget.water_required_liters:g} لتر، والمياه المتاحة "
            f"{budget.water_available_liters:g} لتر، والعجز التقديري {budget.water_shortage_liters:g} لتر."
        )
    else:
        financial = (
            "Break-even price is unavailable because marketable quantity is zero or unknown."
            if finance.break_even_jod_per_kg is None else
            f"Projected total cost is {finance.projected_total_cost_jod:g} JOD and the estimated "
            f"break-even price is {finance.break_even_jod_per_kg:g} JOD per kg."
        )
        water = (
            "Water shortage cannot be calculated because demand or period-matched water availability is missing."
            if any(value is None for value in (budget.water_required_liters, budget.water_available_liters, budget.water_shortage_liters)) else
            f"Estimated demand is {budget.water_required_liters:g} liters, available water is "
            f"{budget.water_available_liters:g} liters, and estimated shortage is {budget.water_shortage_liters:g} liters."
        )
    return {"finance": financial, "water": water}


def _numbers_are_grounded(answer: str, dashboard: DashboardResponse) -> bool:
    """Accept numbers only inside an exact trusted metric-and-unit sentence."""
    spans = []
    for language in ("ar", "en"):
        for claim in _metric_claims(language, dashboard).values():
            start = answer.find(claim)
            if start >= 0:
                spans.append((start, start + len(claim)))
    return all(
        any(start <= match.start() and match.end() <= end for start, end in spans)
        for match in _NUMBER_PATTERN.finditer(answer)
    )


def _render_answer(language: str, dashboard: DashboardResponse, topic: str, source: RetrievedPassage) -> str:
    claims = _metric_claims(language, dashboard)
    if topic == "finance":
        core = claims["finance"]
        tail = "هذه نتيجة تقديرية وليست ضمانا للربح." if language == "ar" else "This estimate does not guarantee profit."
    elif topic == "inspection":
        assessment = dashboard.inspection.assessment
        if language == "ar":
            state = {"favorable": "توجد ظروف تستدعي الفحص", "not_favorable": "لم تُفعّل قاعدة فحص", "cannot_assess": "تعذر التقييم بسبب نقص البيانات"}[assessment]
            core = f"حالة الفحص البيئي الحالية: {state}. افحص الأوراق والسيقان والثمار ميدانيا وسجل الأعراض، ولا تعتبر المظهر أو الطقس تشخيصا."
            tail = "هذه مؤشرات للفحص فقط، وليست توصية علاجية."
        else:
            state = {"favorable": "conditions warrant inspection", "not_favorable": "no inspection rule triggered", "cannot_assess": "cannot be assessed because data is missing"}[assessment]
            core = f"Current environmental inspection: {state}. Inspect leaves, stems, and fruit and record symptoms; appearance and weather are not a diagnosis."
            tail = "These indicators do not prescribe treatment."
    else:
        core = claims["water"]
        tail = "لم يتم استنتاج انخفاض في المحصول من هذا العجز." if language == "ar" else "No yield reduction was inferred from this shortage."
    citation = f"المصدر: {source.title}." if language == "ar" else f"Source: {source.title}."
    return f"{core} {citation} {tail}"


def _fallback_answer(language: str, dashboard: DashboardResponse, passages: list[RetrievedPassage]) -> str:
    if not passages:
        return (
            "لم أجد مقطعا معرفيا مراجعا ذا صلة بهذا السؤال. يمكنني شرح حسابات المزرعة المسجلة، لكن لا أملك مصدرا يدعم إجابة زراعية محددة هنا."
            if language == "ar" else
            "No relevant reviewed knowledge passage was found for this question. I can explain recorded farm calculations, but I cannot substantiate a specific agronomic answer here."
        )
    source = passages[0]
    return _render_answer(language, dashboard, _topic(source), source)


def _prompt_context(request: AssistantRequest, dashboard: DashboardResponse, passages: list[RetrievedPassage]) -> list[dict[str, str]]:
    context = {
        "question": request.question,
        "language": request.language,
        "calculator_results": dashboard.model_dump(mode="json"),
        "reviewed_passages": [p.model_dump(mode="json") for p in passages],
        "allowed_choices": [{"topic": _topic(p), "source_id": p.id} for p in passages],
    }
    system = (
        "Select one allowed topic and source_id that best answers the question. "
        "Return only a JSON object with language, topic, and source_id. "
        "Copy the requested language exactly. Do not write answer prose, numbers, diagnosis, "
        "pesticide treatment, or database commands. The server renders validated facts."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]


def _groq_answer(request: AssistantRequest, dashboard: DashboardResponse, passages: list[RetrievedPassage]) -> str:
    client = Groq(api_key=settings.groq_api_key, timeout=GROQ_TIMEOUT_SECONDS, max_retries=0)
    completion = client.chat.completions.create(
        model=settings.groq_model,
        messages=_prompt_context(request, dashboard, passages),
        response_format={"type": "json_object"},
        temperature=0.1,
        max_completion_tokens=160,
    )
    content = completion.choices[0].message.content
    if not isinstance(content, str) or len(content) > 1000:
        raise ValueError("Groq returned invalid structured output")
    try:
        selection = _ProviderSelection.model_validate_json(content)
    except (ValidationError, ValueError) as exc:
        raise ValueError("Groq returned invalid structured output") from exc
    if selection.language != request.language:
        raise ValueError("Groq selected the wrong language")
    source = next((p for p in passages if p.id == selection.source_id and _topic(p) == selection.topic), None)
    if source is None:
        raise ValueError("Groq selected an unsupported topic or source")
    answer = _render_answer(request.language, dashboard, selection.topic, source)
    if not _numbers_are_grounded(answer, dashboard):
        raise ValueError("Rendered answer has an unsupported metric or unit")
    return answer


def answer_question(database: Session, request: AssistantRequest) -> AssistantResponse:
    """Read dashboard and reviewed passages; provider may only select validated evidence."""
    dashboard = build_dashboard(database, request.farm_id)
    passages = _relevant_passages(retrieve_passages(request.question, request.language, limit=3), request.language)
    used_fallback = not bool(settings.groq_api_key) or not passages
    answer = ""
    if not used_fallback:
        try:
            answer = _groq_answer(request, dashboard, passages)
        except Exception:
            used_fallback = True
    if used_fallback:
        answer = _fallback_answer(request.language, dashboard, passages)
    return AssistantResponse.model_validate({
        "answer": answer,
        "language": request.language,
        "used_fallback": used_fallback,
        "calculator_references": _calculator_references(dashboard),
        "document_references": _document_references(passages),
        "limitations": _limitations(request.language, dashboard),
    })

