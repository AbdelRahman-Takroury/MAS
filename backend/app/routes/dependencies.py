"""Shared ownership and resource-loading dependencies."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import CropSeason, Farm, Plot


AMMAN_TIMEZONE = ZoneInfo("Asia/Amman")


def owned_farm(database: Session, farm_id: str) -> Farm:
    farm = database.scalar(
        select(Farm).where(Farm.id == farm_id, Farm.owner_id == settings.demo_user_id)
    )
    if farm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found")
    return farm


def owned_season(database: Session, crop_season_id: str) -> CropSeason:
    season = database.scalar(
        select(CropSeason)
        .join(Plot, CropSeason.plot_id == Plot.id)
        .join(Farm, Plot.farm_id == Farm.id)
        .where(CropSeason.id == crop_season_id, Farm.owner_id == settings.demo_user_id)
    )
    if season is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop season not found")
    return season


def normalize_timestamp(timestamp: datetime) -> datetime:
    """Store one unambiguous instant regardless of the caller's UTC offset."""
    return timestamp.astimezone(timezone.utc)


def aware_utc(timestamp: datetime) -> datetime:
    """SQLite test storage drops tzinfo; PostgreSQL retains it."""
    return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp


def ensure_activity_date(season: CropSeason, timestamp: datetime) -> None:
    if timestamp.astimezone(AMMAN_TIMEZONE).date() < season.establishment_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Activity date cannot be before the crop establishment date",
        )
