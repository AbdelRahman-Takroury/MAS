"""Application adapter checks using deterministic Weather Engine responses."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.config import settings
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import CropSeason, Farm, Plot, User
from backend.app.services import dashboard as dashboard_service
from backend.app.services import assistant as assistant_service


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session.begin() as database:
        user = User(id=settings.demo_user_id, preferred_language="ar")
        farm = Farm(
            id="dashboard_farm",
            owner=user,
            location_name="Jordan Valley test farm",
            latitude=Decimal("32.19"),
            longitude=Decimal("35.62"),
            timezone="Asia/Amman",
            is_sample=True,
        )
        plot = Plot(id="dashboard_plot", farm=farm, name="Tomato", area_m2=Decimal("1000"))
        plot.crop_seasons.append(
            CropSeason(
                id="dashboard_season",
                crop="tomato",
                establishment_date=date(2026, 9, 1),
                establishment_method="transplanted",
                crop_stage="mid_season",
                irrigation_method="drip",
                irrigation_efficiency=Decimal("0.9"),
                effective_rain_fraction=Decimal("0.8"),
                system_flow_liters_per_hour=None,
                expected_marketable_kg=Decimal("2000"),
                assumed_sale_price_jod_per_kg=Decimal("0.6"),
                water_available_liters=Decimal("4000"),
                water_period_start=datetime.now(ZoneInfo("Asia/Amman")).date(),
                water_period_end=datetime.now(ZoneInfo("Asia/Amman")).date() + timedelta(days=6),
                water_allocation_is_demo=True,
                is_active=True,
            )
        )
        database.add(user)

    def override_database():
        database = testing_session()
        try:
            yield database
        finally:
            database.close()

    monkeypatch.setattr(dashboard_service, "get_weather", lambda *_args, **_kwargs: live_weather())
    app.dependency_overrides[get_db] = override_database
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def live_weather(status="live"):
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Asia/Amman")).date()
    return {
        "status": status,
        "source": "open-meteo",
        "data_type": "forecast",
        "timezone": "Asia/Amman",
        "retrieved_at": now.isoformat().replace("+00:00", "Z"),
        "forecast_start_date": today.isoformat(),
        "forecast_end_date": (today + timedelta(days=6)).isoformat(),
        "summary": {"requested_days": 7, "status": "complete"},
        "units": {"et0": "mm/day", "precipitation": "mm"},
        "warnings": [],
        "advisories": [],
        "daily": [
            {
                "date": (today + timedelta(days=index)).isoformat(),
                "temperature_max_c": 31,
                "temperature_min_c": 20,
                "relative_humidity_mean_percent": 55,
                "relative_humidity_hours_available": 24,
                "relative_humidity_hours_expected": 24,
                "wind_speed_max_kmh": 10,
                "rain_probability_max_percent": 0,
                "weather_code": 0,
                "et0_mm": 5,
                "precipitation_mm": 0,
            }
            for index in range(7)
        ],
    }


def test_dashboard_integrates_engines_and_does_not_invent_runtime(client):
    response = client.get("/api/farms/dashboard_farm/dashboard")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "farm_id", "generated_at", "is_sample", "weather", "irrigation",
        "water_budget", "finance", "inspection", "actions",
    }
    assert body["weather"]["data_kind"] == "live"
    assert body["irrigation"]["status"] == "estimated"
    assert body["irrigation"]["runtime_hours"] is None
    assert "system_flow_liters_per_hour" in body["irrigation"]["missing_inputs"]
    assert body["water_budget"]["water_status"] == "shortage"
    assert body["finance"]["projected_total_cost_jod"] == 0
    assert body["inspection"]["assessment"] == "not_favorable"


def test_persisted_expense_changes_finance_without_changing_irrigation(client):
    before = client.get("/api/farms/dashboard_farm/dashboard").json()
    created = client.post(
        "/api/expenses",
        json={
            "crop_season_id": "dashboard_season",
            "description": "Drip repair",
            "category": "maintenance",
            "amount_jod": 100,
            "incurred_at": "2026-10-09T09:00:00+03:00",
            "cost_view": "cash",
            "idempotency_key": "dashboard-expense",
        },
    )
    assert created.status_code == 201, created.text
    after = client.get("/api/farms/dashboard_farm/dashboard").json()
    assert after["finance"]["projected_total_cost_jod"] == 100
    assert after["finance"]["projected_profit_jod"] == 1100
    assert after["irrigation"]["water_required_liters"] == before["irrigation"]["water_required_liters"]


def test_cached_weather_provenance_is_preserved(client, monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "get_weather",
        lambda *_args, **_kwargs: live_weather("cached"),
    )
    body = client.get("/api/farms/dashboard_farm/dashboard").json()
    assert body["weather"]["data_kind"] == "cached"
    assert body["irrigation"]["status"] == "estimated"


def test_missing_weather_withholds_demand_and_budget(client, monkeypatch):
    unavailable = live_weather()
    unavailable.update(
        status="unavailable",
        retrieved_at=None,
        forecast_start_date=None,
        forecast_end_date=None,
        daily=[],
        advisories=[],
        warnings=["No usable current weather forecast."],
    )
    unavailable["summary"] = {"requested_days": 7, "status": "unavailable"}
    monkeypatch.setattr(dashboard_service, "get_weather", lambda *_args, **_kwargs: unavailable)
    response = client.get("/api/farms/dashboard_farm/dashboard")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["weather"]["status"] == "unavailable"
    assert body["irrigation"]["water_required_liters"] is None
    assert body["water_budget"]["water_shortage_liters"] is None
    assert body["inspection"]["assessment"] == "cannot_assess"


@pytest.mark.parametrize("field", ["temperature_max_c", "relative_humidity_mean_percent"])
def test_partial_inspection_evidence_cannot_assess(client, monkeypatch, field):
    partial = live_weather()
    partial["daily"][0][field] = None
    monkeypatch.setattr(dashboard_service, "get_weather", lambda *_args, **_kwargs: partial)
    inspection = client.get("/api/farms/dashboard_farm/dashboard").json()["inspection"]
    assert inspection["status"] == "missing_data"
    assert inspection["assessment"] == "cannot_assess"
    assert inspection["alerts"] == []
    assert inspection["missing_inputs"] == ["temperature or humidity data"]
    assert inspection["limitations"] == [
        "Environmental conditions could not be fully assessed."
    ]


def test_triggered_weather_advisory_is_favorable_inspection_condition(client, monkeypatch):
    triggered = live_weather()
    triggered["advisories"] = [
        {
            "date": triggered["daily"][0]["date"],
            "type": "heat_inspection",
            "message": "High temperatures are forecast. Inspect tomato plants.",
        }
    ]
    monkeypatch.setattr(dashboard_service, "get_weather", lambda *_args, **_kwargs: triggered)
    inspection = client.get("/api/farms/dashboard_farm/dashboard").json()["inspection"]
    assert inspection["status"] == "ok"
    assert inspection["assessment"] == "favorable"
    assert inspection["alerts"] == [
        f"{triggered['daily'][0]['date']}: High temperatures are forecast. Inspect tomato plants."
    ]
    assert "not a disease diagnosis" in inspection["warnings"][0]


def test_unknown_farm_is_404(client):
    assert client.get("/api/farms/not-owned/dashboard").status_code == 404


def test_simulation_changes_scenario_without_persisting_overrides(client):
    dashboard_before = client.get("/api/farms/dashboard_farm/dashboard").json()
    response = client.post(
        "/api/farms/dashboard_farm/simulate",
        json={
            "overrides": {
                "water_available_liters": 3000,
                "expected_marketable_kg": 1800,
                "sale_price_jod_per_kg": 0.55,
                "additional_costs_jod": 75,
            }
        },
    )
    assert response.status_code == 200, response.text
    simulation = response.json()
    assert simulation["persisted"] is False
    assert simulation["water_budget"]["data_kind"] == "simulated"
    assert simulation["water_budget"]["water_available_liters"] == 3000
    assert simulation["finance"]["data_kind"] == "simulated"
    assert simulation["finance"]["projected_total_cost_jod"] == 75
    assert simulation["finance"]["expected_marketable_kg"] == 1800
    assert simulation["finance"]["assumed_sale_price_jod_per_kg"] == 0.55
    assert simulation["finance"]["projected_revenue_jod"] == 990
    assert simulation["finance"]["projected_profit_jod"] == 915
    assert simulation["unsupported_effects"] == [
        "No yield response to water shortage was modeled."
    ]

    dashboard_after = client.get("/api/farms/dashboard_farm/dashboard").json()
    assert dashboard_after["water_budget"]["water_available_liters"] == 4000
    assert dashboard_after["finance"] == {
        **dashboard_before["finance"],
        "generated_at": dashboard_after["finance"]["generated_at"],
    }


def test_simulation_adds_scenario_costs_to_persisted_expenses(client):
    created = client.post(
        "/api/expenses",
        json={
            "crop_season_id": "dashboard_season",
            "description": "Recorded labor",
            "category": "labor",
            "amount_jod": 100,
            "incurred_at": "2026-10-09T09:00:00+03:00",
            "cost_view": "cash",
            "idempotency_key": "simulation-recorded-cost",
        },
    )
    assert created.status_code == 201
    simulation = client.post(
        "/api/farms/dashboard_farm/simulate",
        json={"overrides": {"additional_costs_jod": 25}},
    ).json()
    assert simulation["finance"]["projected_total_cost_jod"] == 125
    assert simulation["finance"]["projected_profit_jod"] == 1075
    assert client.get("/api/farms/dashboard_farm/dashboard").json()["finance"][
        "projected_total_cost_jod"
    ] == 100


def test_zero_harvest_returns_unavailable_break_even_without_division(client):
    response = client.post(
        "/api/farms/dashboard_farm/simulate",
        json={"overrides": {"expected_marketable_kg": 0}},
    )
    assert response.status_code == 200, response.text
    finance = response.json()["finance"]
    assert finance["status"] == "missing_data"
    assert finance["expected_marketable_kg"] == 0
    assert finance["break_even_jod_per_kg"] is None
    assert finance["projected_revenue_jod"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"overrides": {}},
        {"overrides": {"expected_marketable_kg": -1}},
        {"overrides": {"sale_price_jod_per_kg": -0.1}},
        {"overrides": {"additional_costs_jod": -1}},
        {"overrides": {"water_available_liters": -1}},
    ],
)
def test_invalid_simulation_overrides_are_422(client, payload):
    assert client.post("/api/farms/dashboard_farm/simulate", json=payload).status_code == 422


def test_unknown_simulation_farm_is_404(client):
    response = client.post(
        "/api/farms/not-owned/simulate",
        json={"overrides": {"water_available_liters": 1}},
    )
    assert response.status_code == 404


def test_simulation_baseline_is_from_same_forecast_and_persisted_inputs(client, monkeypatch):
    calls = []
    def weather(*args, **kwargs):
        calls.append(1)
        return live_weather()
    monkeypatch.setattr(dashboard_service, "get_weather", weather)
    result = client.post("/api/ui/farms/dashboard_farm/simulate", json={"overrides": {
        "water_available_liters": 0, "additional_costs_jod": 25,
    }}).json()
    assert len(calls) == 1
    assert result["persisted"] is False
    assert result["baseline"]["water_budget"]["water_available_liters"] == 4000
    assert result["water_budget"]["water_available_liters"] == 0
    assert result["water_budget"]["water_required_liters"] == result["baseline"]["water_budget"]["water_required_liters"]
    assert result["finance"]["projected_total_cost_jod"] == result["baseline"]["finance"]["projected_total_cost_jod"] + 25
    stored = client.get("/api/farms/dashboard_farm/dashboard").json()
    assert stored["water_budget"]["water_available_liters"] == 4000


def test_voice_rejects_non_audio_provider_body(client, monkeypatch):
    from backend.app.routes import voice
    from io import BytesIO
    monkeypatch.setattr(settings, "azure_speech_key", "test-only")
    monkeypatch.setattr(settings, "azure_speech_region", "eastus")
    monkeypatch.setattr(voice, "urlopen", lambda *a, **kw: BytesIO(b"<html>provider error</html>"))
    response = client.post("/api/ui/assistant/voice", json={"farm_id": "dashboard_farm", "recommendation_id": "dashboard_farm-review"})
    assert response.status_code == 503
    assert "audio_url" not in response.json()


class MockGroq:
    init_kwargs = None
    create_kwargs = None
    answer = "تشير لوحة المعلومات إلى عجز تقديري. المصدر: فهم عجز المياه."
    error = None

    def __init__(self, **kwargs):
        type(self).init_kwargs = kwargs
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        type(self).create_kwargs = kwargs
        if type(self).error is not None:
            raise type(self).error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=type(self).answer))]
        )


def test_assistant_uses_configured_model_and_returns_retrieved_citations(
    client, monkeypatch
):
    MockGroq.error = None
    MockGroq.answer = '{"language":"ar","topic":"water","source_id":"water-shortage-limitations-ar"}'
    monkeypatch.setattr(assistant_service, "Groq", MockGroq)
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", "test-secret")
    response = client.post(
        "/api/assistant",
        json={
            "farm_id": "dashboard_farm",
            "language": "ar",
            "question": "لماذا يوجد عجز في المياه؟",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["used_fallback"] is False
    assert body["language"] == "ar"
    assert body["document_references"][0]["document_id"] == "water-shortage-limitations-ar"
    assert body["calculator_references"]
    assert MockGroq.create_kwargs["model"] == assistant_service.settings.groq_model
    assert MockGroq.create_kwargs["model"] == "openai/gpt-oss-20b"
    assert MockGroq.init_kwargs["timeout"] == 5.0
    assert "test-secret" not in response.text


def test_assistant_without_groq_key_returns_useful_english_fallback(client, monkeypatch):
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", None)
    response = client.post(
        "/api/assistant",
        json={
            "farm_id": "dashboard_farm",
            "language": "en",
            "question": "How is the break-even price calculated?",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["used_fallback"] is True
    assert "break-even" in body["answer"].lower()
    assert "Understanding break-even price" in body["answer"]
    assert body["document_references"][0]["document_id"] == "financial-break-even-en"


def test_assistant_groq_failure_preserves_arabic_fallback_and_sources(client, monkeypatch):
    MockGroq.error = RuntimeError("provider unavailable")
    monkeypatch.setattr(assistant_service, "Groq", MockGroq)
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", "test-secret")
    response = client.post(
        "/api/assistant",
        json={
            "farm_id": "dashboard_farm",
            "language": "ar",
            "question": "كيف أفحص البندورة عند ظهور بقع؟",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["used_fallback"] is True
    assert "افحص" in body["answer"]
    assert body["document_references"]
    assert all(reference["source_url"] for reference in body["document_references"])
    MockGroq.error = None


def test_assistant_rejects_ungrounded_model_number_and_falls_back(client, monkeypatch):
    MockGroq.error = None
    MockGroq.answer = "القيمة المؤكدة هي 999999. المصدر: فهم عجز المياه."
    monkeypatch.setattr(assistant_service, "Groq", MockGroq)
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", "test-secret")
    body = client.post(
        "/api/assistant",
        json={
            "farm_id": "dashboard_farm",
            "language": "ar",
            "question": "لماذا يوجد عجز في المياه؟",
        },
    ).json()
    assert body["used_fallback"] is True
    assert "999999" not in body["answer"]


def test_assistant_unknown_farm_is_404(client, monkeypatch):
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", None)
    response = client.post(
        "/api/assistant",
        json={"farm_id": "not-owned", "language": "en", "question": "Why?"},
    )
    assert response.status_code == 404


def _session_from_client():
    provider = app.dependency_overrides[get_db]()
    return provider, next(provider)


def test_metric_grounding_binds_values_to_metric_and_unit(client):
    from backend.app.schemas.dashboard import DashboardResponse

    dashboard = DashboardResponse.model_validate(client.get("/api/farms/dashboard_farm/dashboard").json())
    claim = assistant_service._metric_claims("en", dashboard)["water"]
    assert assistant_service._numbers_are_grounded(claim, dashboard)
    available = dashboard.water_budget.water_available_liters
    assert available is not None
    assert not assistant_service._numbers_are_grounded(
        f"Estimated demand is {available:g} liters.", dashboard
    )
    assert not assistant_service._numbers_are_grounded(
        f"Available water is {available:g} kg.", dashboard
    )
    cost = dashboard.finance.projected_total_cost_jod
    assert not assistant_service._numbers_are_grounded(
        f"Break-even price is {cost:g} JOD per kg.", dashboard
    )


@pytest.mark.parametrize("provider_output", [
    "Apply 4000 liters; spray fungicide. Source: فهم عجز المياه.",
    '{"language":"ar","topic":"water","source_id":"water-shortage-limitations-ar","answer":"spray fungicide"}',
    '{"language":"en","topic":"water","source_id":"water-shortage-limitations-ar"}',
    '{"language":"ar","topic":"finance","source_id":"water-shortage-limitations-ar"}',
    '{"language":"ar","topic":"water","source_id":"financial-break-even-en"}',
    '{"language":"ar","topic":"water","source_id":"made-up-document"}',
    "{not-json}",
])
def test_assistant_rejects_adversarial_provider_output(client, monkeypatch, provider_output):
    MockGroq.error = None
    MockGroq.answer = provider_output
    monkeypatch.setattr(assistant_service, "Groq", MockGroq)
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", "test-secret")
    body = client.post("/api/assistant", json={
        "farm_id": "dashboard_farm", "language": "ar", "question": "لماذا يوجد عجز في المياه؟",
    }).json()
    assert body["used_fallback"] is True
    assert "رش" not in body["answer"] and "spray" not in body["answer"]
    assert body["language"] == "ar"
    assert "المصدر:" in body["answer"]
    assert all(ref["source_url"] for ref in body["document_references"])


def test_assistant_timeout_uses_useful_english_fallback(client, monkeypatch):
    MockGroq.error = TimeoutError("provider timed out")
    monkeypatch.setattr(assistant_service, "Groq", MockGroq)
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", "test-secret")
    body = client.post("/api/assistant", json={
        "farm_id": "dashboard_farm", "language": "en",
        "question": "How is the break-even price calculated?",
    }).json()
    assert body["used_fallback"] is True
    assert "break-even" in body["answer"].lower()
    assert "Understanding break-even price" in body["answer"]
    MockGroq.error = None


def test_irrelevant_retrieval_is_explicit_and_uncited(client, monkeypatch):
    MockGroq.error = None
    MockGroq.create_kwargs = None
    monkeypatch.setattr(assistant_service, "Groq", MockGroq)
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", "test-secret")
    body = client.post("/api/assistant", json={
        "farm_id": "dashboard_farm", "language": "en", "question": "quantum telescope",
    }).json()
    assert body["used_fallback"] is True
    assert "No relevant reviewed knowledge passage" in body["answer"]
    assert body["document_references"] == []
    assert MockGroq.create_kwargs is None


def test_arabic_question_mark_still_retrieves_relevant_passage(client, monkeypatch):
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", None)
    body = client.post("/api/assistant", json={
        "farm_id": "dashboard_farm", "language": "ar", "question": "كيف أقدر الري؟",
    }).json()
    assert body["document_references"]
    assert body["document_references"][0]["document_id"] == "water-shortage-limitations-ar"


def test_arabic_finance_fallback_uses_reviewed_cross_language_source(client, monkeypatch):
    monkeypatch.setattr(assistant_service.settings, "groq_api_key", None)
    body = client.post("/api/assistant", json={
        "farm_id": "dashboard_farm", "language": "ar", "question": "ما سعر التعادل؟",
    }).json()
    assert body["used_fallback"] is True
    assert "سعر التعادل" in body["answer"]
    assert body["document_references"][0]["document_id"] == "financial-break-even-en"


def test_recommendations_use_current_weather_and_label_seeded_demo(client):
    body = client.get("/api/ui/farms/dashboard_farm/recommendations").json()
    cards = body["recommendations"]
    assert cards[0]["id"] == "dashboard_farm-review"
    assert all(card["evidence"] and card["action"]["ar"] and card["why"]["en"]
               and card["limitations"] for card in cards)
    demo = next(card for card in cards if any(e["key"] == "seeded_allocation" for e in card["evidence"]))
    assert demo["topic"] == "irrigation"
    assert any(e["value"] == 4000 for e in demo["evidence"])
    assert "demonstration" in demo["summary"]["en"].lower()
    assert all("pesticide" not in card["action"]["en"].lower() for card in cards)


def test_recommendations_surface_missing_water_and_finance_without_inventing_zero(client):
    provider, db = _session_from_client()
    try:
        season = db.get(CropSeason, "dashboard_season")
        season.water_available_liters = None
        season.water_period_start = None
        season.water_period_end = None
        season.expected_marketable_kg = None
        season.assumed_sale_price_jod_per_kg = None
        db.commit()
    finally:
        provider.close()
    cards = client.get("/api/ui/farms/dashboard_farm/recommendations").json()["recommendations"]
    water = next(card for card in cards if "Water shortage cannot" in card["summary"]["en"])
    assert any(e["key"] == "water_availability" and e["value"] == {"en": "unknown", "ar": "غير معروفة"}
               for e in water["evidence"])
    assert not any(e["key"] == "water_shortage" for e in water["evidence"])
    finance = next(card for card in cards if card["topic"] == "finance")
    assert "expected remaining" in finance["action"]["en"]
    assert "سعر البيع" in finance["action"]["ar"]


def test_recommendations_report_partial_forecast_fields(client, monkeypatch):
    weather = live_weather()
    weather["daily"][0]["et0_mm"] = None
    monkeypatch.setattr(dashboard_service, "get_weather", lambda *_args, **_kwargs: weather)
    cards = client.get("/api/ui/farms/dashboard_farm/recommendations").json()["recommendations"]
    first = cards[0]
    assert first["id"] == "dashboard_farm-review"
    assert "incomplete coverage" in first["summary"]["en"]
    evidence = {item["key"]: item["value"] for item in first["evidence"]}
    assert evidence["complete_forecast_days"] < evidence["requested_forecast_days"]
    assert "reference evapotranspiration" in evidence["missing_weather_fields"]["en"]
    assert first["sources"][0]["url"] == "https://open-meteo.com/"


def test_recommendations_do_not_treat_missing_forecast_or_demo_allocation_as_real(client, monkeypatch):
    weather = live_weather(status="unavailable")
    weather["daily"] = []
    monkeypatch.setattr(dashboard_service, "get_weather", lambda *_args, **_kwargs: weather)
    cards = client.get("/api/ui/farms/dashboard_farm/recommendations").json()["recommendations"]
    assert "No usable forecast" in cards[0]["summary"]["en"]
    water = next(card for card in cards if "Water shortage cannot" in card["summary"]["en"])
    assert "forecast" in water["action"]["en"].lower()
    saved = next(e for e in water["evidence"] if e["key"] == "saved_allocation")
    assert "demo" in saved["label"]["en"].lower()
    assert not any(e["key"] == "water_shortage" for e in water["evidence"])


def test_recommendations_change_with_recorded_season_data(client):
    before = client.get("/api/ui/farms/dashboard_farm/recommendations").json()["recommendations"]
    assert not any(any(e["key"] == "recorded_expenses" for e in card["evidence"]) for card in before)
    provider, db = _session_from_client()
    try:
        from backend.app.models import Expense
        db.add(Expense(id="test-expense", crop_season_id="dashboard_season",
                       description="Recorded labor", category="labor",
                       amount_jod=Decimal("12.500"), incurred_at=datetime.now(timezone.utc),
                       idempotency_key="test-expense"))
        db.commit()
    finally:
        provider.close()
    after = client.get("/api/ui/farms/dashboard_farm/recommendations").json()["recommendations"]
    record = next(card for card in after if any(e["key"] == "recorded_expenses" for e in card["evidence"]))
    assert {e["key"]: e["value"] for e in record["evidence"]}["recorded_expenses"] == 12.5
    assert record["sources"][0]["title"]["en"] == "Active-season farm records"


def test_recommendations_are_isolated_by_farm(client):
    provider, db = _session_from_client()
    try:
        other = Farm(id="other_farm", owner_id=settings.demo_user_id,
                     location_name="Other test farm", latitude=Decimal("31.5"),
                     longitude=Decimal("35.1"), timezone="Asia/Amman", is_sample=False)
        plot = Plot(id="other_plot", farm=other, name="Tomato", area_m2=Decimal("500"))
        plot.crop_seasons.append(CropSeason(
            id="other_season", crop="tomato", establishment_date=date(2026, 9, 1),
            establishment_method="transplanted", crop_stage="mid_season",
            irrigation_method="drip", irrigation_efficiency=Decimal("0.9"),
            effective_rain_fraction=Decimal("0.8"), system_flow_liters_per_hour=None,
            expected_marketable_kg=None, assumed_sale_price_jod_per_kg=None, is_active=True,
        ))
        db.add(other)
        db.commit()
    finally:
        provider.close()
    first = client.get("/api/ui/farms/dashboard_farm/recommendations").json()["recommendations"]
    second = client.get("/api/ui/farms/other_farm/recommendations").json()["recommendations"]
    assert second[0]["id"] == "other_farm-review"
    assert not any(any(e["key"] == "seeded_allocation" for e in card["evidence"]) for card in second)
    assert any("Water shortage cannot" in card["summary"]["en"] for card in second)
    assert any(any(e["key"] == "seeded_allocation" for e in card["evidence"]) for card in first)

