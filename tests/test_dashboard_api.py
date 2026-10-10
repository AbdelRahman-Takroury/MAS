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
    MockGroq.answer = "تشير لوحة المعلومات إلى عجز تقديري. المصدر: فهم عجز المياه."
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
