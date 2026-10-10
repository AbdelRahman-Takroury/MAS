"""Transactional request receipts and recovery after a competing insert commits."""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from ..models import WriteReceipt


def request_digests(payload):
    def canonical(value):
        if isinstance(value, Decimal):
            return format(value.normalize(), 'f') if value else '0'
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, dict):
            return {key: canonical(item) for key, item in value.items()}
        if isinstance(value, list):
            return [canonical(item) for item in value]
        return jsonable_encoder(value)
    raw = payload.model_dump(mode='python')
    digest = hashlib.sha256(json.dumps(canonical(raw), sort_keys=True).encode()).hexdigest()
    # Accept receipts produced by the previous UI implementation as well.
    legacy = hashlib.sha256(json.dumps(jsonable_encoder(payload), sort_keys=True).encode()).hexdigest()
    digests = [digest, legacy]
    water_fields = ('water_available_liters', 'water_period_start', 'water_period_end')
    if all(name in raw and raw[name] is None for name in water_fields):
        old_raw = {key: value for key, value in raw.items() if key not in water_fields}
        old_json = {key: value for key, value in jsonable_encoder(payload).items() if key not in water_fields}
        digests.extend(hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
                       for value in (canonical(old_raw), old_json))
    return tuple(digests)


def receipt_response(db, scope, key, digests):
    prior = db.get(WriteReceipt, (scope, key))
    if prior is None:
        return None
    if prior.digest not in digests:
        raise HTTPException(409, 'Idempotency key was already used with different data')
    return json.loads(prior.response_json)


def create_once(db, *, scope, key, payload, lookup, same_payload, build, response):
    digests = request_digests(payload)
    previous = receipt_response(db, scope, key, digests)
    if previous is not None:
        return previous

    def legacy_response():
        row = db.scalar(lookup)
        if row is None:
            return None
        if not same_payload(row, payload):
            raise HTTPException(409, 'Idempotency key was already used with different data')
        return response(row)

    previous = legacy_response()
    if previous is not None:
        return previous
    try:
        row = build()
        db.add(row)
        db.flush()
        db.refresh(row)
        data = jsonable_encoder(response(row))
        db.add(WriteReceipt(scope=scope, key=key, digest=digests[0], response_json=json.dumps(data)))
        db.commit()
        return data
    except IntegrityError:
        db.rollback()  # A fresh READ COMMITTED snapshot can see the winning transaction.
        previous = receipt_response(db, scope, key, digests)
        if previous is not None:
            return previous
        previous = legacy_response()
        if previous is not None:
            return previous
        raise HTTPException(409, 'Record conflicts with existing data')
