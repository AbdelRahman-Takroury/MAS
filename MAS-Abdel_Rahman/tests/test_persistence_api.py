"""Integration tests for the minimum persistence API using isolated SQLite storage."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.config import settings
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import User


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session.begin() as database:
        database.add(User(id=settings.demo_user_id, preferred_language="ar"))

    def override_database():
        database = testing_session()
        try:
            yield database
        finally:
            database.close()

    app.dependency_overrides[get_db] = override_database
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def farm_payload():
    return {
        "farm_id": "api_test_farm",
        "location_name": "Jordan Valley test farm",
        "latitude": 32.19,
        "longitude": 35.62,
        "timezone": "Asia/Amman",
        "area_m2": 1000,
        "crop": "tomato",
        "establishment_date": "2026-09-01",
        "establishment_method": "transplanted",
        "crop_stage": "mid_season",
        "irrigation_method": "drip",
        "irrigation_efficiency": 0.9,
        "effective_rain_fraction": 0.8,
        "system_flow_liters_per_hour": None,
        "preferred_language": "ar",
        "is_sample": True,
    }


def create_farm(client, payload):
    response = client.post("/api/farms", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_retrieve_farm(client, farm_payload):
    created = create_farm(client, farm_payload)
    retrieved = client.get(f"/api/farms/{farm_payload['farm_id']}")
    assert retrieved.status_code == 200
    assert retrieved.json() == created
    assert created["crop_season_id"]


def test_duplicate_farm_is_conflict(client, farm_payload):
    create_farm(client, farm_payload)
    assert client.post("/api/farms", json=farm_payload).status_code == 409


def test_expense_replay_is_idempotent_and_mismatch_conflicts(client, farm_payload):
    farm = create_farm(client, farm_payload)
    payload = {
        "crop_season_id": farm["crop_season_id"],
        "description": "Drip line repair",
        "category": "maintenance",
        "amount_jod": 12.5,
        "incurred_at": "2026-10-09T09:00:00+03:00",
        "cost_view": "cash",
        "idempotency_key": "expense-test-001",
    }
    first = client.post("/api/expenses", json=payload)
    replay = client.post("/api/expenses", json=payload)
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    changed = deepcopy(payload)
    changed["amount_jod"] = 99
    assert client.post("/api/expenses", json=changed).status_code == 409
    listed = client.get(f"/api/farms/{farm_payload['farm_id']}/expenses")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_irrigation_is_confirmed_and_idempotent(client, farm_payload):
    farm = create_farm(client, farm_payload)
    payload = {
        "crop_season_id": farm["crop_season_id"],
        "occurred_at": "2026-10-09T07:00:00+03:00",
        "amount_liters": 3500,
        "duration_hours": 2,
        "system_flow_liters_per_hour": 1750,
        "measurement_basis": "calibrated",
        "idempotency_key": "irrigation-test-001",
    }
    first = client.post("/api/irrigations", json=payload)
    replay = client.post("/api/irrigations", json=payload)
    assert first.status_code == replay.status_code == 201
    assert first.json()["status"] == "confirmed"
    assert first.json()["id"] == replay.json()["id"]
    listed = client.get(f"/api/farms/{farm_payload['farm_id']}/irrigations")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


@pytest.mark.parametrize("endpoint", ["expenses", "irrigations"])
def test_activity_before_establishment_is_rejected(client, farm_payload, endpoint):
    farm = create_farm(client, farm_payload)
    if endpoint == "expenses":
        payload = {
            "crop_season_id": farm["crop_season_id"],
            "description": "Old expense",
            "category": "other",
            "amount_jod": 1,
            "incurred_at": "2026-08-31T09:00:00+03:00",
            "cost_view": "cash",
            "idempotency_key": "old-expense",
        }
    else:
        payload = {
            "crop_season_id": farm["crop_season_id"],
            "occurred_at": "2026-08-31T09:00:00+03:00",
            "amount_liters": 1,
            "measurement_basis": "unknown",
            "idempotency_key": "old-irrigation",
        }
    assert client.post(f"/api/{endpoint}", json=payload).status_code == 422


def test_naive_activity_timestamp_is_rejected(client, farm_payload):
    farm = create_farm(client, farm_payload)
    response = client.post(
        "/api/expenses",
        json={
            "crop_season_id": farm["crop_season_id"],
            "description": "No timezone",
            "category": "other",
            "amount_jod": 1,
            "incurred_at": "2026-10-09T09:00:00",
            "cost_view": "cash",
            "idempotency_key": "naive-time",
        },
    )
    assert response.status_code == 422


def test_unknown_resources_do_not_leak(client):
    assert client.get("/api/farms/not-owned").status_code == 404
    assert client.get("/api/farms/not-owned/expenses").status_code == 404
    assert client.get("/api/farms/not-owned/irrigations").status_code == 404
