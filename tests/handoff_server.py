"""Opt-in local QA server. Refuses databases not named mas_handoff_*.

Weather is synthetic; Groq and Azure are disabled. This is never a live-provider check.
"""
import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--port', type=int, default=8891)
    parser.add_argument('--host', choices=['127.0.0.1', '0.0.0.0'], default='127.0.0.1')
    args = parser.parse_args()
    from sqlalchemy.engine import make_url
    url = make_url(args.database_url)
    if not Path(url.database or '').name.startswith('mas_handoff_'):
        raise SystemExit('Refusing a database without the mas_handoff_ prefix')
    os.environ.update(DATABASE_URL=args.database_url, GROQ_API_KEY='', AZURE_SPEECH_KEY='',
                      AZURE_SPEECH_REGION='', DEMO_USER_ID='demo_user_001')
    os.chdir(ROOT)
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    from backend.app.seed import seed_demo
    seed_demo()
    from backend.app.services import dashboard
    def forecast(*_args, **_kwargs):
        now = datetime.now(timezone.utc)
        today = now.astimezone(ZoneInfo('Asia/Amman')).date()
        return {
            'status': 'live', 'source': 'open-meteo', 'data_type': 'forecast',
            'timezone': 'Asia/Amman', 'retrieved_at': now.isoformat(),
            'forecast_start_date': today.isoformat(), 'forecast_end_date': (today + timedelta(days=6)).isoformat(),
            'summary': {'requested_days': 7, 'status': 'complete'},
            'units': {'et0': 'mm/day', 'precipitation': 'mm'}, 'warnings': ['Synthetic QA forecast'], 'advisories': [],
            'daily': [{'date': (today + timedelta(days=i)).isoformat(), 'temperature_max_c': 31,
                       'temperature_min_c': 20, 'relative_humidity_mean_percent': 55,
                       'relative_humidity_hours_available': 24, 'relative_humidity_hours_expected': 24,
                       'wind_speed_max_kmh': 10, 'rain_probability_max_percent': 0, 'weather_code': 0,
                       'et0_mm': 5, 'precipitation_mm': 0} for i in range(7)],
        }
    dashboard.get_weather = forecast
    from backend.app.main import app
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == '__main__':
    main()
