"""Idempotently seed the canonical hackathon farm, plot, and crop season."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal

from .database import SessionLocal
from .models import CropSeason, Farm, Plot, User


DEMO_USER_ID = "demo_user_001"
DEMO_FARM_ID = "demo_farm_001"
DEMO_PLOT_ID = "demo_plot_001"
DEMO_SEASON_ID = "demo_season_001"


def seed_demo() -> None:
    today = datetime.now(ZoneInfo("Asia/Amman")).date()
    with SessionLocal.begin() as session:
        if session.get(User, DEMO_USER_ID) is None:
            session.add(User(id=DEMO_USER_ID, preferred_language="ar"))

        if session.get(Farm, DEMO_FARM_ID) is None:
            session.add(
                Farm(
                    id=DEMO_FARM_ID,
                    owner_id=DEMO_USER_ID,
                    location_name="Jordan Valley - sample farm",
                    latitude=Decimal("32.190000"),
                    longitude=Decimal("35.620000"),
                    timezone="Asia/Amman",
                    is_sample=True,
                )
            )

        if session.get(Plot, DEMO_PLOT_ID) is None:
            session.add(
                Plot(
                    id=DEMO_PLOT_ID,
                    farm_id=DEMO_FARM_ID,
                    name="Sample tomato plot",
                    area_m2=Decimal("1000.000"),
                )
            )

        if session.get(CropSeason, DEMO_SEASON_ID) is None:
            session.add(
                CropSeason(
                    id=DEMO_SEASON_ID,
                    plot_id=DEMO_PLOT_ID,
                    crop="tomato",
                    establishment_date=date(2026, 9, 1),
                    establishment_method="transplanted",
                    crop_stage="mid_season",
                    irrigation_method="drip",
                    irrigation_efficiency=Decimal("0.90000"),
                    effective_rain_fraction=Decimal("0.80000"),
                    system_flow_liters_per_hour=None,
                    expected_marketable_kg=Decimal("2000.000"),
                    assumed_sale_price_jod_per_kg=Decimal("0.6000"),
                    water_available_liters=Decimal("4000.000"),
                    water_period_start=today,
                    water_period_end=today + timedelta(days=6),
                    water_allocation_is_demo=True,
                    is_active=True,
                )
            )


if __name__ == "__main__":
    seed_demo()
    print(f"Seeded demo farm {DEMO_FARM_ID} and crop season {DEMO_SEASON_ID}.")
