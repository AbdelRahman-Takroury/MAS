from fastapi.testclient import TestClient
import pytest

from app import team_engines
from app import main as api_main
from app.database import add_weather_coordinates, make_engine
from app.main import create_app
from app.seed import seed


@pytest.fixture
def client():
    app = create_app("sqlite:///:memory:")
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


def create_farm(client):
    response = client.post("/api/farms", json={
        "name": "Test tomato farm", "location": "Jordan Valley", "area_dunum": 3,
        "planting_date": "2026-08-01", "crop_stage": "vegetative", "irrigation_method": "drip",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_farm_crud_and_validation(client):
    farm_id = create_farm(client)
    assert client.get("/api/farms").json()["farms"][0]["id"] == farm_id
    assert client.get(f"/api/farms/{farm_id}").json()["origin"] == "api"
    assert client.patch(f"/api/farms/{farm_id}", json={"area_dunum": 4}).json()["area_dunum"] == 4
    assert client.put(f"/api/farms/{farm_id}", json={"name": "Updated farm"}).status_code == 200
    assert client.post("/api/farms", json={"name": "", "area_dunum": -1}).status_code == 422
    assert client.get("/api/farms/missing").status_code == 404
    assert client.delete(f"/api/farms/{farm_id}").status_code == 204
    assert client.get(f"/api/farms/{farm_id}").status_code == 404


def test_farm_creation_is_idempotent(client):
    body = {"name": "Idempotent farm"}
    key = {"Idempotency-Key": "farm-create-1"}
    one = client.post("/api/farms", json=body, headers=key)
    two = client.post("/api/farms", json=body, headers=key)
    assert one.json()["id"] == two.json()["id"]
    assert client.post("/api/farms", json={"name": "Different"}, headers=key).status_code == 409


def test_irrigation_crud_idempotency_and_validation(client):
    farm_id = create_farm(client)
    url = f"/api/farms/{farm_id}/irrigation"
    body = {"date": "2026-10-07", "confirmed": True, "amount_mm": 12}
    headers = {"Idempotency-Key": "irrigation-entry-1"}
    first = client.post(url, json=body, headers=headers)
    second = client.post(url, json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get(url).json()["records"]) == 1
    missing_estimate = client.get(url).json()["estimate"]
    assert missing_estimate["status"] == "unavailable"
    assert missing_estimate["value"] is None
    assert "latitude" in missing_estimate["missing_inputs"]
    assert client.post(url, json={**body, "amount_mm": 13}, headers=headers).status_code == 409
    assert client.post(url, json={"date": "bad", "amount_mm": -1}).status_code == 422
    record_id = first.json()["id"]
    assert client.patch(f"{url}/{record_id}", json={"confirmed": False}).status_code == 200
    assert client.get(f"{url}/{record_id}").json()["confirmed"] is False
    assert client.delete(f"{url}/{record_id}").status_code == 204


def test_expenses_harvest_sales_and_financial_summary(client):
    farm_id = create_farm(client)
    season_body = {
        "name": "2026 season", "start_date": "2026-08-01", "expected_harvest_kg": 1000,
        "projected_costs_jod": 500, "projected_revenue_jod": 900, "fertilizer_budget_jod": 120,
    }
    season = client.post(f"/api/farms/{farm_id}/seasons", json=season_body, headers={"Idempotency-Key": "season-1"})
    assert season.status_code == 201, season.text
    season_retry = client.post(f"/api/farms/{farm_id}/seasons", json=season_body, headers={"Idempotency-Key": "season-1"})
    assert season_retry.json()["id"] == season.json()["id"]
    season_id = season.json()["id"]
    headers = {"Idempotency-Key": "expense-1"}
    expense_body = {"date": "2026-10-01", "category": "fertilizer", "amount_jod": 75, "season_id": season_id}
    expense = client.post(f"/api/farms/{farm_id}/expenses", json=expense_body, headers=headers)
    assert expense.status_code == 201, expense.text
    assert client.post(f"/api/farms/{farm_id}/costs", json=expense_body, headers=headers).json()["id"] == expense.json()["id"]
    assert client.get(f"/api/farms/{farm_id}/financials").json()["recorded_costs_jod"] == 75

    harvest = client.post(f"/api/farms/{farm_id}/harvests", json={"date": "2026-10-05", "quantity_kg": 50, "season_id": season_id}, headers={"Idempotency-Key": "harvest-1"})
    assert harvest.status_code == 201, harvest.text
    sale_body = {"date": "2026-10-06", "quantity_kg": 20, "unit_price_jod": 0.8, "harvest_id": harvest.json()["id"]}
    sale = client.post(f"/api/farms/{farm_id}/sales", json=sale_body, headers={"Idempotency-Key": "sale-1"})
    assert sale.status_code == 201, sale.text
    assert sale.json()["total_jod"] == pytest.approx(16)
    summary = client.get(f"/api/farms/{farm_id}/financials").json()
    assert summary["actual_revenue_jod"] == pytest.approx(16)
    assert summary["actual_sold_kg"] == pytest.approx(20)
    assert summary["actual_cost_per_sold_kg_jod"] == pytest.approx(3.75)
    assert summary["actual_harvest_kg"] == pytest.approx(50)
    assert summary["actual_harvest_source"] == "harvest_records"
    assert summary["actual_harvest_scope"] == "all_seasons"
    assert summary["actual_harvest_active_season_kg"] == pytest.approx(50)
    assert summary["projected_costs_jod"] == 500
    assert summary["expected_harvest_kg"] == 1000
    assert summary["expected_harvest_source"] == "farmer_entered"
    assert summary["expected_harvest_scope"] == "active_season"

    assert client.patch(f"/api/farms/{farm_id}/expenses/{expense.json()['id']}", json={"amount_jod": 80}).status_code == 200
    assert client.delete(f"/api/farms/{farm_id}/sales/{sale.json()['id']}").status_code == 204
    assert client.delete(f"/api/farms/{farm_id}/harvests/{harvest.json()['id']}").status_code == 204


def test_fertilizer_catalog_is_sourced_and_compared_to_active_season_budget(client):
    farm_id = create_farm(client)
    url = f"/api/farms/{farm_id}/fertilizers"
    response = client.get(url)
    assert response.status_code == 200
    catalog = response.json()
    assert catalog["origin"] == "supplier_snapshot"
    assert catalog["updated_at"] == "2026-10-10"
    assert catalog["budget_jod"] is None
    assert len(catalog["products"]) >= 3
    product = catalog["products"][0]
    assert product["price_jod"] > 0
    assert product["price_per_kg_jod"] == product["price_jod"] / product["package_quantity"]
    assert product["source_url"].startswith("https://")
    assert product["source_updated"] == catalog["updated_at"]
    assert product["within_budget_for_one_pack"] is None

    season = client.post(f"/api/farms/{farm_id}/seasons", json={
        "name": "Fertilizer comparison", "start_date": "2026-08-01",
        "fertilizer_budget_jod": 4,
    })
    assert season.status_code == 201, season.text
    compared = client.get(url).json()
    assert compared["budget_jod"] == 4
    assert all(item["within_budget_for_one_pack"] is False for item in compared["products"])
    assert all(item["budget_remaining_after_one_pack_jod"] == -1.5 for item in compared["products"])

    budget_update = client.patch(f"/api/farms/{farm_id}/seasons/{season.json()['id']}", json={"fertilizer_budget_jod": 10})
    assert budget_update.status_code == 200
    within = client.get(url).json()
    assert all(item["within_budget_for_one_pack"] is True for item in within["products"])
    assert all(item["budget_remaining_after_one_pack_jod"] == 4.5 for item in within["products"])
    assert client.get("/api/farms/missing/fertilizers").status_code == 404


def test_data_survives_app_restart(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'persistent.sqlite3'}"
    app1 = create_app(db_url)
    with TestClient(app1) as c1:
        farm_id = create_farm(c1)
    app1.state.engine.dispose()
    app2 = create_app(db_url)
    with TestClient(app2) as c2:
        response = c2.get(f"/api/farms/{farm_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Test tomato farm"
    app2.state.engine.dispose()


def test_provider_routes_report_unavailable_data_without_fabricating_values(client, monkeypatch):
    farm_id = create_farm(client)
    assert client.get(f"/api/farms/{farm_id}/weather").json()["days"] == []
    assert client.get(f"/api/farms/{farm_id}/inspections").json()["reminders"] == []
    recs = client.get(f"/api/farms/{farm_id}/recommendations").json()["recommendations"]
    assert recs[0]["topic"] == "data"
    chat = client.post("/api/assistant/chat", json={"message": "hello", "language": "en", "farm_id": farm_id})
    assert chat.status_code == 200 and chat.json()["origin"] == "fallback"
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)
    voice = client.post("/api/assistant/voice", json={"farm_id": farm_id, "recommendation_id": farm_id + "-complete-profile"})
    assert voice.status_code == 503


def test_voice_audio_route_with_mocked_azure_provider(client, monkeypatch):
    farm_id = create_farm(client)
    monkeypatch.setenv("AZURE_SPEECH_KEY", "test-key")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "jordan-central")
    class FakeAudio:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return b"mock-mp3-audio"
    monkeypatch.setattr(api_main, "urlopen", lambda *_args, **_kwargs: FakeAudio())
    response = client.post("/api/assistant/voice", json={"farm_id": farm_id, "recommendation_id": farm_id + "-complete-profile"})
    assert response.status_code == 200
    assert response.json()["voice_id"] == "ar-JO-TaimNeural"
    audio = client.get(response.json()["audio_url"])
    assert audio.content == b"mock-mp3-audio"
    assert audio.headers["content-type"].startswith("audio/mpeg")


def test_groq_chat_provider_request_and_secret_not_returned(client, monkeypatch):
    farm_id = create_farm(client)
    monkeypatch.setenv("GROQ_API_KEY", "server-test-secret")
    class FakeChat:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return b'{"choices":[{"message":{"content":"Use the recorded farm data and verify missing inputs."}}]}'
    monkeypatch.setattr(api_main, "urlopen", lambda *_args, **_kwargs: FakeChat())
    response = client.post("/api/assistant/chat", json={"farm_id": farm_id, "language": "en", "message": "What should I do?"})
    assert response.status_code == 200
    assert response.json()["origin"] == "api"
    assert "server-test-secret" not in response.text


def test_weather_adapter_and_irrigation_engine_integration(client, monkeypatch):
    farm_id = create_farm(client)
    assert client.patch(f"/api/farms/{farm_id}", json={
        "latitude": 32.19, "longitude": 35.62, "crop_stage": "vegetative",
        "irrigation_efficiency": 0.9, "effective_rain_fraction": 0.8,
    }).status_code == 200
    monkeypatch.setattr(team_engines.weather, "get_weather", lambda *args, **kwargs: {
        "status": "live", "source": "open-meteo", "retrieved_at": "2026-10-10T09:00:00Z",
        "forecast_start_date": "2026-10-10", "daily": [{"date": "2026-10-10", "weather_code": 61,
            "temperature_max_c": 30, "temperature_min_c": 20, "precipitation_mm": 2}],
        "summary": {"status": "complete"}, "warnings": [], "advisories": [],
    })
    seen = {}
    def fake_irrigation(farm, _weather, **_kwargs):
        seen.update(farm)
        return {"summary": {"status": "calculated", "total_gross_irrigation_liters": 1234}, "warnings": [], "assumptions": []}
    monkeypatch.setattr(team_engines.irrigation, "calculate_irrigation", fake_irrigation)
    forecast = client.get(f"/api/farms/{farm_id}/weather").json()
    assert forecast["source"] == "open-meteo"
    assert forecast["days"][0]["condition"] == "rain"
    irrigation = client.get(f"/api/farms/{farm_id}/irrigation").json()
    assert irrigation["estimate"]["value"] == 1234
    assert "mapped to engine stage 'development'" in irrigation["estimate"]["warnings"][0]
    assert seen["area_m2"] == 3000
    assert seen["crop_stage"] == "development"
    assert seen["irrigation_efficiency"] == 0.9


def test_weather_missing_coordinates_and_unknown_code_are_explicit(client, monkeypatch):
    farm_id = create_farm(client)
    response = client.get(f"/api/farms/{farm_id}/weather").json()
    assert response["status"] == "unavailable"
    assert response["missing_inputs"] == ["latitude", "longitude"]
    assert response["days"] == []

    client.patch(f"/api/farms/{farm_id}", json={"latitude": 32.1, "longitude": 35.6})
    monkeypatch.setattr(team_engines.weather, "get_weather", lambda *args, **kwargs: {
        "status": "live", "source": "open-meteo", "retrieved_at": "2026-10-10T09:00:00Z",
        "forecast_start_date": "2026-10-10", "daily": [{"date": "2026-10-10", "weather_code": 999,
            "temperature_max_c": None, "temperature_min_c": 19, "precipitation_mm": None}],
        "summary": {}, "warnings": [], "errors": [],
    })
    day = client.get(f"/api/farms/{farm_id}/weather").json()["days"][0]
    assert day["condition"] == "unknown"
    assert day["high"] is None and day["rain_mm"] is None


def test_irrigation_does_not_estimate_unsupported_method(client, monkeypatch):
    farm_id = create_farm(client)
    client.patch(f"/api/farms/{farm_id}", json={"latitude": 32.1, "longitude": 35.6,
        "irrigation_method": "sprinkler", "area_dunum": 2})
    monkeypatch.setattr(team_engines.weather, "get_weather", lambda *args, **kwargs: {
        "status": "live", "source": "open-meteo", "retrieved_at": "2026-10-10T09:00:00Z",
        "forecast_start_date": "2026-10-10", "daily": [], "summary": {}, "warnings": [], "advisories": [],
    })
    called = False
    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("unsupported irrigation method must not be estimated")
    monkeypatch.setattr(team_engines.irrigation, "calculate_irrigation", forbidden)
    estimate = client.get(f"/api/farms/{farm_id}/irrigation").json()["estimate"]
    assert estimate["status"] == "unavailable"
    assert estimate["value"] is None
    assert "supported_drip_method" in estimate["missing_inputs"]
    assert not called


def test_legacy_database_upgrade_only_labels_sample_farm_assumptions(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE farms (id VARCHAR(64), data_origin VARCHAR(16), location VARCHAR(240))")
        connection.exec_driver_sql("INSERT INTO farms VALUES ('demo', 'sample', 'Jordan Valley (sample)')")
        connection.exec_driver_sql("INSERT INTO farms VALUES ('user', 'api', 'Jordan Valley')")
    add_weather_coordinates(engine)
    with engine.connect() as connection:
        demo = connection.exec_driver_sql("SELECT latitude, longitude, irrigation_efficiency, effective_rain_fraction FROM farms WHERE id='demo'").one()
        user = connection.exec_driver_sql("SELECT latitude, longitude FROM farms WHERE id='user'").one()
    assert tuple(float(value) for value in demo) == (32.19, 35.62, 0.9, 0.8)
    assert user.latitude is None and user.longitude is None
    engine.dispose()


def test_farm_coordinate_pair_validation(client):
    response = client.post("/api/farms", json={"name": "Bad coordinates", "latitude": 32})
    assert response.status_code == 422


def test_cors_preflight_allows_configured_frontend(client):
    response = client.options("/api/farms", headers={
        "Origin": "http://localhost:5500",
        "Access-Control-Request-Method": "GET",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"


def test_seed_is_labeled_and_does_not_overwrite_existing_data(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'seed.sqlite3'}"
    assert seed(db_url) == 3
    assert seed(db_url) == 0
    app = create_app(db_url)
    with TestClient(app) as seeded_client:
        farms = seeded_client.get("/api/farms").json()
        assert farms["origin"] == "sample"
        assert len(farms["farms"]) == 3
        assert all(farm["origin"] == "sample" for farm in farms["farms"])
        farm_a = seeded_client.get("/api/farms/a").json()
        assert farm_a["latitude"] == pytest.approx(32.19)
        assert farm_a["irrigation_efficiency"] == pytest.approx(0.9)
    app.state.engine.dispose()
