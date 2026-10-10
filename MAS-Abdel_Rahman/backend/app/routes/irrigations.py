"""Confirmed irrigation-event persistence endpoints."""

from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CropSeason, Farm, IrrigationEvent, Plot
from ..schemas import IrrigationCreate, IrrigationResponse
from .dependencies import (
    aware_utc,
    ensure_activity_date,
    normalize_timestamp,
    owned_farm,
    owned_season,
)


router = APIRouter(tags=["irrigations"])


def _response(event: IrrigationEvent) -> IrrigationResponse:
    return IrrigationResponse(
        id=event.id,
        crop_season_id=event.crop_season_id,
        occurred_at=aware_utc(event.occurred_at),
        amount_liters=float(event.amount_liters),
        duration_hours=float(event.duration_hours) if event.duration_hours is not None else None,
        system_flow_liters_per_hour=(
            float(event.system_flow_liters_per_hour)
            if event.system_flow_liters_per_hour is not None
            else None
        ),
        measurement_basis=event.measurement_basis,
        status="confirmed",
        idempotency_key=event.idempotency_key,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _same_payload(existing: IrrigationEvent, payload: IrrigationCreate) -> bool:
    return (
        aware_utc(existing.occurred_at) == normalize_timestamp(payload.occurred_at)
        and existing.amount_liters == Decimal(str(payload.amount_liters))
        and existing.duration_hours
        == (Decimal(str(payload.duration_hours)) if payload.duration_hours is not None else None)
        and existing.system_flow_liters_per_hour
        == (
            Decimal(str(payload.system_flow_liters_per_hour))
            if payload.system_flow_liters_per_hour is not None
            else None
        )
        and existing.measurement_basis == payload.measurement_basis
    )


@router.post(
    "/api/irrigations", response_model=IrrigationResponse, status_code=status.HTTP_201_CREATED
)
def create_irrigation(
    payload: IrrigationCreate, database: Session = Depends(get_db)
) -> IrrigationResponse:
    season = owned_season(database, payload.crop_season_id)
    ensure_activity_date(season, payload.occurred_at)
    existing = database.scalar(
        select(IrrigationEvent).where(
            IrrigationEvent.crop_season_id == payload.crop_season_id,
            IrrigationEvent.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if not _same_payload(existing, payload):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was already used with different irrigation data",
            )
        return _response(existing)

    event = IrrigationEvent(
        id=str(uuid4()),
        crop_season_id=payload.crop_season_id,
        occurred_at=normalize_timestamp(payload.occurred_at),
        amount_liters=Decimal(str(payload.amount_liters)),
        duration_hours=(
            Decimal(str(payload.duration_hours)) if payload.duration_hours is not None else None
        ),
        system_flow_liters_per_hour=(
            Decimal(str(payload.system_flow_liters_per_hour))
            if payload.system_flow_liters_per_hour is not None
            else None
        ),
        measurement_basis=payload.measurement_basis,
        status="confirmed",
        idempotency_key=payload.idempotency_key,
    )
    database.add(event)
    database.commit()
    database.refresh(event)
    return _response(event)


@router.get("/api/farms/{farm_id}/irrigations", response_model=list[IrrigationResponse])
def list_irrigations(
    farm_id: str, database: Session = Depends(get_db)
) -> list[IrrigationResponse]:
    owned_farm(database, farm_id)
    records = database.scalars(
        select(IrrigationEvent)
        .join(CropSeason, IrrigationEvent.crop_season_id == CropSeason.id)
        .join(Plot, CropSeason.plot_id == Plot.id)
        .join(Farm, Plot.farm_id == Farm.id)
        .where(Farm.id == farm_id)
        .order_by(IrrigationEvent.occurred_at, IrrigationEvent.id)
    ).all()
    return [_response(item) for item in records]
