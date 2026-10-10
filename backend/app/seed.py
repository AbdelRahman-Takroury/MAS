"""Insert the three existing mock farm profiles only into a completely empty DB."""
from __future__ import annotations

from datetime import date
from sqlalchemy import select

from .database import Base, make_engine, make_session_factory
from .models import Farm

SAMPLE_FARMS = [
    {"id": "a", "name": "Tomato Plot A1", "location": "Jordan Valley (sample)", "latitude": 32.19, "longitude": 35.62, "irrigation_efficiency": 0.9, "effective_rain_fraction": 0.8, "area_dunum": 4, "planting_date": "2026-08-20", "crop_stage": "vegetative", "irrigation_method": "drip"},
    {"id": "b", "name": "Tomato Plot B2", "area_dunum": None},
    {"id": "c", "name": "Tomato Plot C3", "location": "Jordan Valley (sample)", "latitude": 32.19, "longitude": 35.62, "irrigation_efficiency": 0.9, "effective_rain_fraction": 0.8, "area_dunum": 2.5, "planting_date": "2026-09-15", "crop_stage": "flowering", "irrigation_method": "drip"},
]


def seed(url: str | None = None) -> int:
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            if session.scalar(select(Farm.id).limit(1)) is not None:
                return 0
            for item in SAMPLE_FARMS:
                values = dict(item)
                if values.get("planting_date"):
                    values["planting_date"] = date.fromisoformat(values["planting_date"])
                session.add(Farm(**values, data_origin="sample"))
            session.commit()
            return len(SAMPLE_FARMS)
    finally:
        engine.dispose()


if __name__ == "__main__":
    print(f"Inserted {seed()} sample farm profile(s). Existing databases are left unchanged.")
