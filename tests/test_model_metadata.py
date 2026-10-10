"""Fast checks that the ORM metadata keeps the required persistence boundaries."""

from backend.app.database import Base
from backend.app import models  # noqa: F401


def test_minimum_tables_are_registered():
    assert set(Base.metadata.tables) == {
        "users",
        "farms",
        "plots",
        "crop_seasons",
        "expenses",
        "irrigation_events",
    }


def test_activity_records_belong_to_crop_seasons():
    for table_name in ("expenses", "irrigation_events"):
        foreign_keys = {
            foreign_key.target_fullname
            for foreign_key in Base.metadata.tables[table_name].foreign_keys
        }
        assert "crop_seasons.id" in foreign_keys


def test_idempotency_is_scoped_to_crop_season():
    for table_name in ("expenses", "irrigation_events"):
        unique_columns = {
            tuple(column.name for column in constraint.columns)
            for constraint in Base.metadata.tables[table_name].constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert ("crop_season_id", "idempotency_key") in unique_columns
