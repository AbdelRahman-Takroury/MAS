"""Cross-project behavior: one database, unchanged engines, real dashboard DTOs."""
from decimal import Decimal
import pytest
from test_dashboard_api import client  # shared seeded, network-free SQLite fixture
from backend.app.config import settings

ROOT = "/api/ui/farms/dashboard_farm"


def post(client, path, payload, key=None):
    response = client.post(ROOT + path, json=payload, headers={"Idempotency-Key": key} if key else {})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("suffix", ["", "/irrigation", "/expenses", "/harvests", "/sales", "/seasons", "/financials", "/fertilizers", "/weather", "/inspections", "/recommendations"])
def test_dashboard_sections(client, suffix):
    response = client.get(ROOT + suffix)
    assert response.status_code == 200, response.text


def test_shared_records_finance_and_simulation(client):
    expense = post(client, "/expenses", {"date": "2026-10-10", "category": "labor", "amount_jod": 100, "description": "Picking"})
    harvest = post(client, "/harvests", {"date": "2026-10-10", "quantity_kg": 50})
    sale = post(client, "/sales", {"date": "2026-10-10", "quantity_kg": 40, "unit_price_jod": 2, "harvest_id": harvest["id"]})
    post(client, "/irrigation", {"date": "2026-10-10", "volume_m3": 2})
    canonical = client.get("/api/farms/dashboard_farm/expenses").json()
    assert canonical[0]["id"] == expense["id"]
    finance = client.get(ROOT + "/financials").json()
    assert finance["recorded_costs_jod"] == 100
    assert finance["actual_revenue_jod"] == 80
    assert finance["actual_profit_jod"] == -20
    assert finance["actual_harvest_kg"] == 50
    assert finance["actual_sold_kg"] == 40
    assert finance["projected_revenue_jod"] == 1280  # actual + remaining, exactly once
    dashboard = client.get("/api/farms/dashboard_farm/dashboard").json()
    assert dashboard["finance"]["projected_revenue_jod"] == finance["projected_revenue_jod"]
    simulation = client.post(ROOT + "/simulate", json={"overrides": {"sale_price_jod_per_kg": 1}})
    assert simulation.status_code == 200, simulation.text
    assert simulation.json()["persisted"] is False
    assert simulation.json()["finance"]["projected_revenue_jod"] == 2080
    assert client.get(ROOT + "/financials").json() == finance
    assert client.delete(ROOT + "/harvests/" + harvest["id"]).status_code == 409
    assert client.delete(ROOT + "/sales/" + sale["id"]).status_code == 204
    assert client.delete(ROOT + "/harvests/" + harvest["id"]).status_code == 204


def test_idempotency_and_updates(client):
    payload = {"date": "2026-10-10", "category": "labor", "amount_jod": 12.125, "description": "Work"}
    original = post(client, "/expenses", payload, "same-key")
    assert post(client, "/expenses", payload, "same-key") == original
    assert client.post(ROOT + "/expenses", json={**payload, "amount_jod": 13}, headers={"Idempotency-Key": "same-key"}).status_code == 409
    assert len(client.get(ROOT + "/expenses").json()["expenses"]) == 1
    url = ROOT + "/expenses/" + original["id"]
    assert client.patch(url, json={"amount_jod": 20}).status_code == 200
    assert client.get(ROOT + "/financials").json()["recorded_costs_jod"] == 20
    assert client.patch(url, json={"amount_jod": None}).status_code == 422
    assert client.delete(url).status_code == 204


def test_profile_create_validation_update_delete(client):
    payload = {"name": "Integration farm", "location": "Jordan Valley", "latitude": 32.19, "longitude": 35.62,
               "area_dunum": 2, "planting_date": "2026-09-01", "crop_stage": "mid_season"}
    response = client.post("/api/ui/farms", json=payload, headers={"Idempotency-Key": "farm-key"})
    assert response.status_code == 201, response.text
    farm = response.json()
    assert farm["origin"] == "api"
    assert client.post("/api/ui/farms", json=payload, headers={"Idempotency-Key": "farm-key"}).json() == farm
    canonical = client.get("/api/farms/" + farm["id"]).json()
    assert canonical["area_m2"] == 2000
    url = "/api/ui/farms/" + farm["id"]
    assert client.patch(url, json={"latitude": None}).status_code == 422
    assert client.patch(url, json={"irrigation_method": "furrow"}).status_code == 422
    assert client.patch(url, json={"name": "Changed"}).json()["name"] == "Changed"
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_seasons_no_cross_season_finance(client):
    post(client, "/expenses", {"date": "2026-10-10", "category": "labor", "amount_jod": 100})
    new = post(client, "/seasons", {"name": "Next season", "start_date": "2026-10-10", "expected_harvest_kg": 500,
                                   "projected_costs_jod": 50, "assumed_sale_price_jod_per_kg": 1})
    assert new["is_active"] is True
    finance = client.get(ROOT + "/financials").json()
    assert finance["recorded_costs_jod"] == 0
    assert finance["projected_costs_jod"] == 50
    assert finance["projected_revenue_jod"] == 500
    assert sum(s["is_active"] for s in client.get(ROOT + "/seasons").json()["seasons"]) == 1
    assert client.delete(ROOT + "/seasons/" + new["id"]).status_code == 409
    assert client.patch(ROOT + "/seasons/" + new["id"], json={"end_date": "2020-01-01"}).status_code == 422


def test_unknown_price_keeps_break_even(client):
    post(client, "/expenses", {"date": "2026-10-10", "category": "labor", "amount_jod": 100})
    assert client.patch(ROOT + "/seasons/dashboard_season", json={"assumed_sale_price_jod_per_kg": None}).status_code == 200
    finance = client.get(ROOT + "/financials").json()
    assert finance["projected_revenue_jod"] is None
    assert finance["break_even_price_jod"] == .05


@pytest.mark.parametrize("payload", [
    {"date": "2026-10-10", "confirmed": False, "volume_m3": 1},
    {"date": "2026-10-10"},
    {"date": "2026-10-10", "volume_m3": 1, "amount_mm": 2},
    {"date": "2026-10-10", "volume_m3": 1, "season_id": "other-farm-season"},
])
def test_invalid_irrigation(client, payload):
    assert client.post(ROOT + "/irrigation", json=payload).status_code == 422


def test_chat_fallback_and_whitespace(client, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", None)
    for lang, question in [("ar", "كيف أقدر الري؟"), ("en", "How much irrigation?")]:
        response = client.post("/api/ui/assistant/chat", json={"farm_id": "dashboard_farm", "language": lang, "message": question})
        assert response.status_code == 200, response.text
        assert response.json()["origin"] == "fallback"
        assert response.json()["sources"]
    assert client.post("/api/ui/assistant/chat", json={"farm_id": "dashboard_farm", "message": "   "}).status_code == 422


def test_static_allowlist(client):
    for path in ["/", "/dashboard.html", "/js/api.js", "/js/manage.js", "/css/dashboard.css", "/assets/fonts/Amiri-Regular.ttf"]:
        assert client.get(path).status_code == 200
    for path in ["/.env", "/backend/app/config.py", "/.git/config", "/smart_farm.db", "/api/not-a-route"]:
        assert client.get(path).status_code == 404
    assert "'/api/ui'" in client.get("/dashboard.html").text
    assert settings.groq_model == "openai/gpt-oss-20b"


def test_voice_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "azure_speech_key", None)
    response = client.post("/api/ui/assistant/voice", json={"farm_id": "dashboard_farm", "recommendation_id": "dashboard_farm-review"})
    assert response.status_code == 503


def test_voice_mocked_provider(client, monkeypatch):
    from backend.app.routes import voice
    from io import BytesIO
    monkeypatch.setattr(settings, "azure_speech_key", "test-not-a-real-key")
    monkeypatch.setattr(settings, "azure_speech_region", "eastus")
    monkeypatch.setattr(voice, "urlopen", lambda *args, **kwargs: BytesIO(b"test-mp3"))
    response = client.post("/api/ui/assistant/voice", json={"farm_id": "dashboard_farm", "recommendation_id": "dashboard_farm-review"})
    assert response.status_code == 200, response.text
    audio = client.get(response.json()["audio_url"])
    assert audio.content == b"test-mp3"
    assert audio.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("kind", ["days", "humidity", "duplicate"])
def test_incomplete_weather_is_not_an_assessment(client, monkeypatch, kind):
    from test_dashboard_api import live_weather
    from backend.app.services import dashboard
    data = live_weather()
    if kind == "days":
        data["daily"] = data["daily"][:1]
    elif kind == "humidity":
        data["daily"][0]["relative_humidity_hours_available"] = 1
    else:
        data["daily"][1] = data["daily"][0]
    monkeypatch.setattr(dashboard, "get_weather", lambda *args, **kwargs: data)
    response = client.get(ROOT + "/inspections")
    assert response.status_code == 200
    assert response.json()["assessment"] == "cannot_assess"
    assert response.json()["reminders"][0]["id"] == "cannot-assess"


def test_canonical_assistant_rejects_blank(client):
    assert client.post("/api/assistant", json={"farm_id": "dashboard_farm", "question": "   "}).status_code == 422


def test_unsupported_number_with_unit_is_rejected(client):
    from backend.app.services.assistant import _numbers_are_grounded
    from backend.app.schemas.dashboard import DashboardResponse
    dashboard = DashboardResponse.model_validate(client.get("/api/farms/dashboard_farm/dashboard").json())
    assert not _numbers_are_grounded("Apply 999999L", dashboard)
    assert not _numbers_are_grounded("Apply 9e99 L", dashboard)
