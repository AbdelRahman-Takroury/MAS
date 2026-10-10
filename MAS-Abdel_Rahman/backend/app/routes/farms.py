"""Farm profile persistence endpoints."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import CropSeason, Farm, Plot, User
from ..schemas import FarmCreate, FarmResponse
from .dependencies import owned_farm


router = APIRouter(prefix="/api/farms", tags=["farms"])


def _response(farm: Farm, plot: Plot, season: CropSeason, language: str) -> FarmResponse:
    return FarmResponse(
        farm_id=farm.id,
        location_name=farm.location_name,
        latitude=float(farm.latitude),
        longitude=float(farm.longitude),
        timezone=farm.timezone,
        area_m2=float(plot.area_m2),
        crop=season.crop,
        establishment_date=season.establishment_date,
        establishment_method=season.establishment_method,
        crop_stage=season.crop_stage,
        irrigation_method=season.irrigation_method,
        irrigation_efficiency=(
            float(season.irrigation_efficiency) if season.irrigation_efficiency is not None else None
        ),
        effective_rain_fraction=(
            float(season.effective_rain_fraction) if season.effective_rain_fraction is not None else None
        ),
        system_flow_liters_per_hour=(
            float(season.system_flow_liters_per_hour)
            if season.system_flow_liters_per_hour is not None
            else None
        ),
        preferred_language=language,
        is_sample=farm.is_sample,
        plot_id=plot.id,
        crop_season_id=season.id,
        created_at=farm.created_at,
        updated_at=farm.updated_at,
    )


@router.post("", response_model=FarmResponse, status_code=status.HTTP_201_CREATED)
def create_farm(payload: FarmCreate, database: Session = Depends(get_db)) -> FarmResponse:
    if database.get(Farm, payload.farm_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Farm already exists")

    user = database.get(User, settings.demo_user_id)
    if user is None:
        user = User(id=settings.demo_user_id, preferred_language=payload.preferred_language)
        database.add(user)
    else:
        user.preferred_language = payload.preferred_language

    farm = Farm(
        id=payload.farm_id,
        owner_id=user.id,
        location_name=payload.location_name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        timezone=payload.timezone,
        is_sample=payload.is_sample,
    )
    plot = Plot(
        id=str(uuid4()), farm=farm, name=f"{payload.crop.title()} plot", area_m2=payload.area_m2
    )
    season = CropSeason(
        id=str(uuid4()),
        plot=plot,
        crop=payload.crop,
        establishment_date=payload.establishment_date,
        establishment_method=payload.establishment_method,
        crop_stage=payload.crop_stage,
        irrigation_method=payload.irrigation_method,
        irrigation_efficiency=payload.irrigation_efficiency,
        effective_rain_fraction=payload.effective_rain_fraction,
        system_flow_liters_per_hour=payload.system_flow_liters_per_hour,
        is_active=True,
    )
    database.add(farm)
    database.commit()
    database.refresh(farm)
    database.refresh(plot)
    database.refresh(season)
    return _response(farm, plot, season, user.preferred_language)


@router.get("/{farm_id}", response_model=FarmResponse)
def get_farm(farm_id: str, database: Session = Depends(get_db)) -> FarmResponse:
    farm = owned_farm(database, farm_id)
    plot = next(iter(farm.plots), None)
    season = next((item for item in plot.crop_seasons if item.is_active), None) if plot else None
    if plot is None or season is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Farm has no active crop season",
        )
    return _response(farm, plot, season, farm.owner.preferred_language)
