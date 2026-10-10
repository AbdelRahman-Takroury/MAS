"""Dated allocations and per-farm weather fallback, with no live provider calls."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, MetaData, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.config import settings
from backend.app.main import app
from backend.app.models import CropSeason
from backend.app.services import dashboard
from backend.app.services.weather_metadata import farm_snapshot_path, coverage_metadata
from backend.services import weather
from test_dashboard_api import client, live_weather
from test_weather import synthetic_payload, NOW
from test_write_integrity import concurrent_db

ROOT = '/api/ui/farms/dashboard_farm'
SEASON = ROOT + '/seasons/dashboard_season'
BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Live weather HTTP is not permitted in these tests')
    monkeypatch.setattr(weather, 'urlopen', forbidden)


def allocation(amount=2500):
    data = live_weather()
    return {'water_available_liters': amount, 'water_period_start': data['forecast_start_date'],
            'water_period_end': data['forecast_end_date']}


def budget(client):
    result = client.get('/api/farms/dashboard_farm/dashboard')
    assert result.status_code == 200, result.text
    return result.json()['water_budget']


def test_allocation_persists_and_zero_is_not_unknown(client):
    for value in (2500, 0):
        saved = client.patch(SEASON, json=allocation(value))
        assert saved.status_code == 200, saved.text
        assert saved.json()['water_available_liters'] == value
        canonical = client.get('/api/farms/dashboard_farm').json()
        assert Decimal(str(canonical['water_available_liters'])) == value
        result = budget(client)
        assert result['water_available_liters'] == value
        assert result['availability_source'] == 'user_entered'
        assert result['water_shortage_liters'] > 0
    assert client.patch(SEASON, json={key: None for key in allocation()}).status_code == 200
    result = budget(client)
    assert result['status'] == 'missing_data'
    assert result['water_required_liters'] is not None
    assert result['water_available_liters'] is None
    assert result['water_shortage_liters'] is None
    assert result['coverage_percentage'] is None
    assert 'water_available_liters' in result['missing_inputs']


def test_new_real_farm_never_inherits_demo_water(client):
    result = client.post('/api/ui/farms', json={'name': 'Real', 'location': 'Valley', 'latitude': 32.1,
        'longitude': 35.6, 'area_dunum': 1, 'planting_date': '2026-09-01', 'crop_stage': 'mid_season'})
    assert result.status_code == 201
    data = client.get('/api/farms/' + result.json()['id'] + '/dashboard').json()['water_budget']
    assert data['water_available_liters'] is None
    assert data['allocation_liters'] is None
    assert data['availability_source'] == 'missing_data'


@pytest.mark.parametrize('changes', [
    {'water_available_liters': -1}, {'water_available_liters': 'NaN'},
    {'water_available_liters': '0.0001'}, {'water_available_liters': '10000000000000'},
    {'water_period_start': None}, {'water_period_end': '2026-08-01'},
    {'water_period_start': '2026-08-01'}, {'end_date': '2026-09-01'},
])
def test_allocation_validation_rejects_invalid_partial_updates(client, changes):
    assert client.patch(SEASON, json={**allocation(), **changes}).status_code == 422


def test_allocation_dates_must_match_forecast_without_prorating(client):
    data = allocation()
    data['water_period_end'] = (date.fromisoformat(data['water_period_end']) + timedelta(days=1)).isoformat()
    assert client.patch(SEASON, json=data).status_code == 200
    result = budget(client)
    assert result['allocation_liters'] == 2500
    assert result['water_available_liters'] is None
    assert result['water_shortage_liters'] is None
    assert 'water_allocation_matching_forecast_period' in result['missing_inputs']


def test_expired_allocation_remains_visible_but_not_used(client):
    assert client.patch(SEASON, json={'water_available_liters': 9000,
        'water_period_start': '2026-09-01', 'water_period_end': '2026-09-07'}).status_code == 200
    result = budget(client)
    assert result['allocation_liters'] == 9000
    assert result['water_period_end'] == '2026-09-07'
    assert result['water_available_liters'] is None


@pytest.mark.parametrize('unknown', [False, True])
def test_simulations_never_persist_water_overrides(client, unknown):
    values = {key: None for key in allocation()} if unknown else allocation()
    assert client.patch(SEASON, json=values).status_code == 200
    before = budget(client)
    for overrides in ({'water_available_liters': 0}, {'water_available_liters': 8000}, {'additional_costs_jod': 5}):
        response = client.post(ROOT + '/simulate', json={'overrides': overrides})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['persisted'] is False
        assert data['water_budget']['water_available_liters'] == overrides.get('water_available_liters', before['water_available_liters'])
    after = budget(client)
    for key in ('allocation_liters', 'water_available_liters', 'water_period_start', 'water_period_end', 'availability_source'):
        assert before[key] == after[key]


@pytest.mark.parametrize('language,question', [('ar', 'لماذا يوجد عجز في المياه؟'), ('en', 'Why is there a water shortage?')])
def test_assistant_handles_unknown_water_without_inventing_zero(client, monkeypatch, language, question):
    monkeypatch.setattr(settings, 'groq_api_key', None)
    client.patch(SEASON, json={key: None for key in allocation()})
    response = client.post('/api/assistant', json={'farm_id': 'dashboard_farm', 'language': language, 'question': question})
    assert response.status_code == 200, response.text
    assert response.json()['used_fallback'] is True
    assert '0' not in response.json()['answer']


def test_allocation_survives_connection_restart(concurrent_db, monkeypatch):
    engine, sessions = concurrent_db
    monkeypatch.setattr(dashboard, 'get_weather', lambda *args, **kwargs: live_weather())
    with TestClient(app) as client:
        assert client.patch(SEASON, json=allocation(1234.125)).status_code == 200
    engine.dispose()
    with sessions() as db:
        row = db.get(CropSeason, 'dashboard_season')
        assert row.water_available_liters == Decimal('1234.125')
        assert row.water_period_start.isoformat() == allocation()['water_period_start']


@pytest.mark.parametrize('origin', ['live', 'cached'])
def test_coverage_is_independent_of_provenance(client, monkeypatch, origin):
    result = live_weather(origin)
    result['daily'][0]['et0_mm'] = None
    result['daily'][1]['relative_humidity_hours_available'] = 12
    monkeypatch.setattr(dashboard, 'get_weather', lambda *args, **kwargs: result)
    canonical = client.get('/api/farms/dashboard_farm/dashboard').json()['weather']
    ui = client.get(ROOT + '/weather').json()
    assert canonical['status'] == 'missing_data'
    assert canonical['data_kind'] == origin
    assert ui['status'] == origin
    assert canonical['coverage_status'] == ui['coverage_status'] == 'partial'
    assert ui['coverage']['complete_days'] == 5
    assert ui['coverage']['available_days_per_field']['et0_mm'] == 6
    assert ui['fetched_at'] == result['retrieved_at']
    assert any('et0_mm' in field for field in ui['missing_inputs'])


def test_unavailable_weather_does_not_claim_cached_data(client, monkeypatch):
    result = {'status': 'unavailable', 'daily': [], 'summary': {}, 'warnings': [], 'retrieved_at': None}
    monkeypatch.setattr(dashboard, 'get_weather', lambda *args, **kwargs: result)
    data = client.get('/api/farms/dashboard_farm/dashboard').json()['weather']
    assert data['status'] == data['coverage_status'] == 'unavailable'
    assert data['data_kind'] is None
    assert data['source']['retrieved_at'] is None


@pytest.fixture
def live_cache(client, monkeypatch, tmp_path, synthetic_payload):
    monkeypatch.setattr(settings, 'weather_cache_dir', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(dashboard, 'get_weather', weather.get_weather)
    monkeypatch.setattr(weather, '_utc_now', lambda: NOW)
    monkeypatch.setattr(weather, '_fetch_weather', lambda *args: deepcopy(synthetic_payload))
    return client, tmp_path / 'snapshots'


def offline(*args):
    raise URLError('mocked provider outage')


def test_dashboard_saves_live_and_reuses_original_timestamp(live_cache, monkeypatch):
    client, folder = live_cache
    first = client.get(ROOT + '/weather').json()
    assert first['status'] == 'live'
    assert first['coverage_status'] == 'complete'
    assert len(list(folder.glob('*.json'))) == 1
    monkeypatch.setattr(weather, '_fetch_weather', offline)
    cached = client.get(ROOT + '/weather').json()
    assert cached['status'] == 'cached'
    assert cached['fetched_at'] == first['fetched_at']
    assert cached['coverage_status'] == 'complete'
    monkeypatch.setattr(weather, '_utc_now', lambda: NOW + timedelta(hours=25))
    stale = client.get(ROOT + '/weather').json()
    assert stale['status'] == stale['coverage_status'] == 'unavailable'
    assert stale['fetched_at'] is None


@pytest.mark.parametrize('kind', ['partial', 'malformed'])
def test_bad_live_forecast_never_overwrites_complete_cache(live_cache, monkeypatch, synthetic_payload, kind):
    client, folder = live_cache
    client.get(ROOT + '/weather')
    path = next(folder.glob('*.json'))
    saved = path.read_bytes()
    payload = deepcopy(synthetic_payload)
    if kind == 'partial':
        payload['daily']['et0_fao_evapotranspiration'][0] = None
    else:
        payload = {}
    monkeypatch.setattr(weather, '_fetch_weather', lambda *args: payload)
    data = client.get(ROOT + '/weather').json()
    assert data['status'] == ('live' if kind == 'partial' else 'cached')
    assert data['coverage_status'] == ('partial' if kind == 'partial' else 'complete')
    assert path.read_bytes() == saved


def test_snapshot_write_failure_keeps_valid_live_result(live_cache, monkeypatch):
    def fail(*args):
        raise OSError('read-only cache')
    monkeypatch.setattr(weather, '_save_snapshot', fail)
    data = live_cache[0].get(ROOT + '/weather').json()
    assert data['status'] == 'live'
    assert data['coverage_status'] == 'complete'
    assert any('not saved' in warning for warning in data['warnings'])


def test_farms_and_changed_coordinates_have_distinct_caches(live_cache, monkeypatch):
    client, folder = live_cache
    client.get(ROOT + '/weather')
    original = {p.name: p.read_bytes() for p in folder.glob('*.json')}
    second = client.post('/api/ui/farms', json={'name': 'Second', 'location': 'Same coordinates',
        'latitude': 32.19, 'longitude': 35.62, 'area_dunum': 1, 'planting_date': '2026-09-01', 'crop_stage': 'mid_season'}).json()['id']
    monkeypatch.setattr(weather, '_fetch_weather', offline)
    assert client.get('/api/ui/farms/' + second + '/weather').json()['status'] == 'unavailable'
    assert client.get(ROOT + '/weather').json()['status'] == 'cached'
    client.patch(ROOT, json={'latitude': 31.5})
    assert client.get(ROOT + '/weather').json()['status'] == 'unavailable'
    assert {p.name: p.read_bytes() for p in folder.glob('*.json')} == original


def test_cache_key_uses_farm_and_both_coordinates(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'weather_cache_dir', str(tmp_path))
    keys = {farm_snapshot_path(SimpleNamespace(id=id, latitude=Decimal(lat), longitude=Decimal(lon)))
            for id, lat, lon in [('a', '32.19', '35.62'), ('b', '32.19', '35.62'),
                                 ('a', '32.190001', '35.62'), ('a', '32.19', '35.620001')]}
    assert len(keys) == 4
    assert all(path.parent == tmp_path for path in keys)


def test_additive_migration_preserves_existing_data_and_seed_is_explicit(tmp_path, monkeypatch):
    from backend.app import seed
    url = 'sqlite+pysqlite:///' + str(tmp_path / 'migrations.sqlite')
    monkeypatch.setattr(settings, 'database_url', url)
    config = Config(str(BASE / 'alembic.ini'))
    config.set_main_option('script_location', str(BASE / 'backend/db/migrations'))
    command.upgrade(config, '20261010_0002')
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(engine)
    with engine.begin() as db:
        db.execute(metadata.tables['users'].insert().values(id='existing', preferred_language='ar'))
        db.execute(metadata.tables['farms'].insert().values(id='existing', owner_id='existing', location_name='Existing',
            latitude=32.19, longitude=35.62, timezone='Asia/Amman', is_sample=False))
        db.execute(metadata.tables['plots'].insert().values(id='existing', farm_id='existing', name='Existing', area_m2=1000))
        db.execute(metadata.tables['crop_seasons'].insert().values(id='existing', plot_id='existing', crop='tomato',
            establishment_date=date(2026, 9, 1), establishment_method='transplanted', crop_stage='mid_season', irrigation_method='drip', is_active=True))
        db.execute(metadata.tables['expenses'].insert().values(id='existing', crop_season_id='existing', description='Keep me',
            category='labor', amount_jod=12.125, incurred_at=NOW, cost_view='cash', idempotency_key='existing'))
    command.upgrade(config, 'head')
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        existing = db.get(CropSeason, 'existing')
        assert existing.water_available_liters is None
        assert existing.water_allocation_is_demo is False
        assert existing.expenses[0].amount_jod == Decimal('12.125')
    monkeypatch.setattr(seed, 'SessionLocal', sessions)
    seed.seed_demo()
    with sessions.begin() as db:
        demo = db.get(CropSeason, seed.DEMO_SEASON_ID)
        assert demo.water_available_liters == 4000
        assert demo.water_allocation_is_demo is True
        assert (demo.water_period_end - demo.water_period_start).days == 6
        demo.water_available_liters = None
        demo.water_period_start = demo.water_period_end = None
        demo.water_allocation_is_demo = False
    seed.seed_demo()
    with sessions() as db:
        assert db.get(CropSeason, seed.DEMO_SEASON_ID).water_available_liters is None
    with pytest.raises(IntegrityError), engine.begin() as db:
        db.execute(text("UPDATE crop_seasons SET water_available_liters=-1 WHERE id='existing'"))
    engine.dispose()


def test_canonical_farm_allocation_fields_round_trip(client):
    payload = {'farm_id': 'water-farm', 'location_name': 'Valley', 'latitude': 32.19, 'longitude': 35.62,
        'area_m2': 1000, 'establishment_date': '2026-09-01', 'establishment_method': 'transplanted',
        'crop_stage': 'mid_season', **allocation('1234.125')}
    created = client.post('/api/farms', json=payload)
    assert created.status_code == 201, created.text
    assert client.get('/api/farms/water-farm').json() == created.json()
    assert Decimal(str(created.json()['water_available_liters'])) == Decimal('1234.125')
    assert created.json()['water_allocation_is_demo'] is False
    assert client.post('/api/farms', json={**payload, 'farm_id': 'invalid-water', 'water_period_end': None}).status_code == 422


def test_new_season_does_not_inherit_previous_allocation(client):
    response = client.post(ROOT + '/seasons', json={'name': 'New', 'start_date': '2026-09-01'})
    assert response.status_code == 201
    assert response.json()['water_available_liters'] is None
    assert budget(client)['water_available_liters'] is None


def test_cached_next_day_forecast_is_partial(live_cache, monkeypatch):
    client, _ = live_cache
    original = client.get(ROOT + '/weather').json()
    monkeypatch.setattr(weather, '_fetch_weather', offline)
    monkeypatch.setattr(weather, '_utc_now', lambda: NOW + timedelta(hours=13))
    result = client.get(ROOT + '/weather').json()
    assert result['status'] == 'cached'
    assert result['coverage_status'] == 'partial'
    assert result['coverage']['available_days'] == 6
    assert result['fetched_at'] == original['fetched_at']


def test_adding_nullable_water_fields_keeps_old_season_receipts(client):
    import hashlib
    import json
    from fastapi.encoders import jsonable_encoder
    from backend.app.database import get_db
    from backend.app.models import WriteReceipt
    from backend.app.schemas.ui import SeasonInput
    payload = {'name': 'Previous', 'start_date': '2026-09-01'}
    old = jsonable_encoder(SeasonInput.model_validate(payload))
    for key in ('water_available_liters', 'water_period_start', 'water_period_end'):
        del old[key]
    digest = hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        db.add(WriteReceipt(scope='dashboard_farm/seasons', key='old-season', digest=digest,
                            response_json=json.dumps({'id': 'original-season'})))
        db.commit()
    finally:
        generator.close()
    response = client.post(ROOT + '/seasons', json=payload, headers={'Idempotency-Key': 'old-season'})
    assert response.status_code == 201
    assert response.json() == {'id': 'original-season'}
