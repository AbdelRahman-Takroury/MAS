"""Expose provenance independently from forecast completeness."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from backend.services.weather import DAILY_FIELDS
from ..config import settings


def farm_snapshot_path(farm):
    identity = json.dumps([farm.id, format(farm.latitude, '.6f'), format(farm.longitude, '.6f')])
    return Path(settings.weather_cache_dir) / (hashlib.sha256(identity.encode()).hexdigest() + '.json')


def coverage_metadata(weather):
    fields = [spec[0] for spec in DAILY_FIELDS.values()] + ['relative_humidity_mean_percent']
    requested = weather.get('summary', {}).get('requested_days', 7)
    daily = weather.get('daily', [])
    try:
        start = date.fromisoformat(weather['forecast_start_date'])
        expected = [(start + timedelta(days=i)).isoformat() for i in range(requested)]
    except (KeyError, TypeError, ValueError):
        expected = []
    rows = {row['date']: row for row in daily if row.get('date') in expected}
    missing = []
    counts = {field: 0 for field in fields}
    complete_days = 0
    for day in expected:
        row = rows.get(day, {})
        good = True
        for field in fields:
            present = row.get(field) is not None
            if field == 'relative_humidity_mean_percent':
                present = present and row.get('relative_humidity_hours_available', 0) == 24
            counts[field] += int(present)
            if not present:
                missing.append(day + ':' + field)
                good = False
        complete_days += int(good)
    if not expected:
        missing.append('current weather forecast')
    if len(daily) != len(rows):
        missing.append('unique forecast dates within the requested period')
    usable = weather.get('status') in ('live', 'cached') and any(counts.values())
    complete = usable and not missing and complete_days == requested and weather.get('summary', {}).get('status') == 'complete'
    if usable and not complete and not missing:
        missing.append('complete forecast coverage')
    return {
        'coverage_status': 'complete' if complete else 'partial' if usable else 'unavailable',
        'coverage': {'requested_days': requested, 'available_days': len(rows), 'complete_days': complete_days,
                     'available_days_per_field': counts,
                     'humidity_hours_available': sum(row.get('relative_humidity_hours_available', 0) for row in rows.values()),
                     'humidity_hours_expected': requested * 24},
        'missing_inputs': missing,
    }
