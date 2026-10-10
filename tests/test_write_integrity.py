"""Public write contracts, real competing transactions, and immutable retry receipts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
import os
import uuid
from sqlalchemy import text
from sqlalchemy.engine import make_url

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import settings
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import User, Farm, Plot, CropSeason, Expense, IrrigationEvent, WriteReceipt
from test_dashboard_api import client

ROOT = '/api/ui/farms/dashboard_farm'
RECORDS = [
    ('expenses', {'category': 'labor', 'description': 'Picking', 'amount_jod': 12.125}),
    ('irrigation', {'volume_m3': 1}),
    ('harvests', {'quantity_kg': 10}),
    ('sales', {'quantity_kg': 10, 'unit_price_jod': 2}),
]


@pytest.mark.parametrize('section,fields', RECORDS)
def test_ui_dates_on_create_and_update(client, section, fields):
    url = ROOT + '/' + section
    assert client.post(url, json={**fields, 'date': '2026-08-31'}).status_code == 422
    created = client.post(url, json={**fields, 'date': '2026-09-01'})
    assert created.status_code == 201, created.text
    record = created.json()
    assert client.patch(url + '/' + record['id'], json={'date': '2026-08-31'}).status_code == 422
    assert client.patch(url + '/' + record['id'], json={'date': '2026-09-02'}).status_code == 200


def canonical_payload(kind, key='retry'):
    common = {'crop_season_id': 'dashboard_season', 'idempotency_key': key}
    if kind == 'expenses':
        return {**common, 'incurred_at': '2026-09-01T00:00:00+03:00', 'amount_jod': '12.125',
                'description': 'Picking', 'category': 'labor'}
    return {**common, 'occurred_at': '2026-09-01T00:00:00+03:00', 'amount_liters': '1000.125',
            'duration_hours': '1.125', 'measurement_basis': 'measured'}


@pytest.mark.parametrize('kind,time_field', [('expenses', 'incurred_at'), ('irrigations', 'occurred_at')])
def test_canonical_date_uses_amman_day(client, kind, time_field):
    payload = canonical_payload(kind)
    payload[time_field] = '2026-08-31T20:59:59Z'
    assert client.post('/api/' + kind, json=payload).status_code == 422
    payload[time_field] = '2026-08-31T21:00:00Z'
    assert client.post('/api/' + kind, json=payload).status_code == 201


@pytest.mark.parametrize('volume', [0, -1, '0.0000001'])
def test_ui_irrigation_positive_on_create_and_update(client, volume):
    url = ROOT + '/irrigation'
    payload = {'date': '2026-09-01', 'volume_m3': volume}
    assert client.post(url, json=payload).status_code == 422
    saved = client.post(url, json={**payload, 'volume_m3': 1}).json()
    assert client.patch(url + '/' + saved['id'], json={'volume_m3': volume}).status_code == 422


@pytest.mark.parametrize('liters', [0, -1, '0.0001'])
def test_canonical_irrigation_positive_storage_precision(client, liters):
    assert client.post('/api/irrigations', json={**canonical_payload('irrigations'), 'amount_liters': liters}).status_code == 422


@pytest.mark.parametrize('api', ['canonical', 'ui'])
@pytest.mark.parametrize('amount', ['12.1251', '-0.001', 'NaN', '100000000000.000'])
def test_money_rejects_values_database_cannot_preserve(client, api, amount):
    if api == 'canonical':
        result = client.post('/api/expenses', json={**canonical_payload('expenses'), 'amount_jod': amount})
    else:
        result = client.post(ROOT + '/expenses', json={'date': '2026-09-01', 'category': 'labor', 'amount_jod': amount})
    assert result.status_code == 422, result.text


@pytest.mark.parametrize('kind', ['expenses', 'irrigations'])
def test_canonical_replay_normalizes_decimal_and_timezone_and_preserves_original(client, kind):
    payload = canonical_payload(kind)
    url = '/api/' + kind
    original = client.post(url, json=payload)
    assert original.status_code == 201, original.text
    body = original.json()
    number = 'amount_jod' if kind == 'expenses' else 'amount_liters'
    timestamp = 'incurred_at' if kind == 'expenses' else 'occurred_at'
    equivalent = {**payload, number: payload[number] + '0', timestamp: '2026-08-31T21:00:00Z'}
    assert client.post(url, json=equivalent).json() == body
    section = 'expenses' if kind == 'expenses' else 'irrigation'
    update = {'amount_jod': 20} if kind == 'expenses' else {'volume_m3': 2}
    assert client.patch(ROOT + '/' + section + '/' + body['id'], json=update).status_code == 200
    assert client.post(url, json=payload).json() == body
    assert client.post(url, json={**payload, number: 25}).status_code == 409


def test_ui_decimal_equivalence_and_original_receipt(client):
    payload = {'date': '2026-09-01', 'category': 'labor', 'amount_jod': '12.100'}
    url = ROOT + '/expenses'
    headers = {'Idempotency-Key': 'precision'}
    original = client.post(url, json=payload, headers=headers).json()
    assert client.post(url, json={**payload, 'amount_jod': 12.1}, headers=headers).json() == original
    assert client.patch(url + '/' + original['id'], json={'amount_jod': 30}).status_code == 200
    assert client.post(url, json=payload, headers=headers).json() == original
    assert client.post(url, json={**payload, 'amount_jod': 40}, headers=headers).status_code == 409


@pytest.fixture
def concurrent_db(tmp_path):
    # Separate connections and sessions; no shared in-memory SQLite connection.
    pg_url = os.environ.get('TEST_POSTGRES_URL')
    admin = None
    if pg_url:
        parsed = make_url(pg_url)
        if parsed.get_backend_name() != 'postgresql' or not (parsed.database or '').startswith('mas_handoff_'):
            raise RuntimeError('TEST_POSTGRES_URL must target an isolated mas_handoff_* PostgreSQL database')
        schema_name = 'race_' + uuid.uuid4().hex
        admin = create_engine(pg_url)
        with admin.begin() as conn:
            conn.execute(text('CREATE SCHEMA ' + schema_name))
        engine = create_engine(pg_url, connect_args={'options': '-csearch_path=' + schema_name})
    else:
        engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'race.sqlite'),
                               connect_args={'check_same_thread': False, 'timeout': 15})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with sessions.begin() as db:
        user = User(id=settings.demo_user_id, preferred_language='ar')
        farm = Farm(id='dashboard_farm', owner=user, location_name='Test', latitude=32.19,
                    longitude=35.62, timezone='Asia/Amman', is_sample=True)
        plot = Plot(id='plot', farm=farm, name='Test', area_m2=Decimal('1000'))
        CropSeason(id='dashboard_season', plot=plot, crop='tomato', establishment_date=date(2026, 9, 1),
                   establishment_method='transplanted', crop_stage='mid_season', irrigation_method='drip', is_active=True)
        db.add(user)
    def override():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        yield engine, sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        if admin is not None:
            with admin.begin() as conn:
                conn.execute(text('DROP SCHEMA ' + schema_name + ' CASCADE'))
            admin.dispose()


@pytest.mark.parametrize('layer,kind', [('canonical', 'expenses'), ('canonical', 'irrigations'), ('ui', 'expenses'), ('ui', 'irrigations')])
@pytest.mark.parametrize('conflict', [False, True])
def test_competing_requests_are_atomic_and_replayable(concurrent_db, layer, kind, conflict):
    engine, sessions = concurrent_db
    barrier = Barrier(2, timeout=10)
    model = Expense if kind == 'expenses' else IrrigationEvent
    def synchronize(db, context, instances):
        if db.bind is engine and not db.info.get('synchronized') and any(isinstance(row, model) for row in db.new):
            db.info['synchronized'] = True
            barrier.wait()  # Both requests have passed the initial receipt/row lookup.
    event.listen(Session, 'before_flush', synchronize)
    payload = canonical_payload(kind)
    if layer == 'canonical':
        url, headers = '/api/' + kind, {}
        field = 'amount_jod' if kind == 'expenses' else 'amount_liters'
    else:
        section = 'expenses' if kind == 'expenses' else 'irrigation'
        url, headers = ROOT + '/' + section, {'Idempotency-Key': 'race'}
        field = 'amount_jod' if kind == 'expenses' else 'volume_m3'
        payload = {'date': '2026-09-01', field: 10}
        if kind == 'expenses':
            payload['category'] = 'labor'
    other = {**payload, field: 20} if conflict else dict(payload)
    try:
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(client.post, url, json=value, headers=headers) for value in (payload, other)]
            responses = [request.result(timeout=20) for request in requests]
            assert sorted(r.status_code for r in responses) == ([201, 409] if conflict else [201, 201]), [r.text for r in responses]
            if not conflict:
                assert responses[0].json() == responses[1].json()
            winner = next(index for index, response in enumerate(responses) if response.status_code == 201)
            retry = client.post(url, json=(payload, other)[winner], headers=headers)
            assert retry.json() == responses[winner].json()
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(model)) == 1
            assert db.scalar(select(func.count()).select_from(WriteReceipt)) == 1
    finally:
        event.remove(Session, 'before_flush', synchronize)


@pytest.mark.parametrize('section,fields', RECORDS)
def test_moving_record_to_later_season_revalidates_date(client, section, fields):
    record = client.post(ROOT + '/' + section, json={**fields, 'date': '2026-09-01'}).json()
    season = client.post(ROOT + '/seasons', json={'name': 'Later', 'start_date': '2026-10-01'}).json()
    result = client.patch(ROOT + '/' + section + '/' + record['id'], json={'season_id': season['id']})
    assert result.status_code == 422, result.text


@pytest.mark.parametrize('profile', [False, True])
def test_season_start_update_cannot_invalidate_existing_records(client, profile):
    client.post(ROOT + '/expenses', json={'date': '2026-09-01', 'category': 'labor', 'amount_jod': 10})
    url = ROOT if profile else ROOT + '/seasons/dashboard_season'
    result = client.patch(url, json={'planting_date' if profile else 'start_date': '2026-09-02'})
    assert result.status_code == 422, result.text
    assert client.get(ROOT).json()['planting_date'] == '2026-09-01'


def test_legacy_receipt_still_replays(client):
    import hashlib
    import json
    from fastapi.encoders import jsonable_encoder
    from backend.app.schemas.ui import ExpenseInput
    payload = {'date': '2026-09-01', 'category': 'labor', 'amount_jod': '12.100'}
    request = ExpenseInput.model_validate(payload)
    old_digest = hashlib.sha256(json.dumps(jsonable_encoder(request), sort_keys=True).encode()).hexdigest()
    # Insert the previous format into the isolated fixture's database.
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        db.add(WriteReceipt(scope='dashboard_farm/expenses', key='old-key', digest=old_digest,
                            response_json=json.dumps({'id': 'historical-result'})))
        db.commit()
    finally:
        generator.close()
    response = client.post(ROOT + '/expenses', json=payload, headers={'Idempotency-Key': 'old-key'})
    assert response.status_code == 201
    assert response.json() == {'id': 'historical-result'}


def test_legacy_canonical_rows_without_receipts_remain_replayable(client):
    payload = canonical_payload('expenses')
    original = client.post('/api/expenses', json=payload).json()
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        db.delete(db.get(WriteReceipt, ('canonical/expenses/dashboard_season', payload['idempotency_key'])))
        db.commit()
    finally:
        generator.close()
    replay = client.post('/api/expenses', json=payload)
    assert replay.status_code == 201
    assert replay.json() == original
