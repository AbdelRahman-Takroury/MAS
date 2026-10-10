"""Crop-season expense persistence endpoints."""

from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CropSeason, Expense, Farm, Plot
from ..schemas import ExpenseCreate, ExpenseResponse
from .idempotency import create_once
from .dependencies import (
    aware_utc,
    ensure_activity_date,
    normalize_timestamp,
    owned_farm,
    owned_season,
)


router = APIRouter(tags=["expenses"])


def _response(expense: Expense) -> ExpenseResponse:
    return ExpenseResponse(
        id=expense.id,
        crop_season_id=expense.crop_season_id,
        description=expense.description,
        category=expense.category,
        amount_jod=float(expense.amount_jod),
        incurred_at=aware_utc(expense.incurred_at),
        cost_view=expense.cost_view,
        idempotency_key=expense.idempotency_key,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )


def _same_payload(existing: Expense, payload: ExpenseCreate) -> bool:
    return (
        existing.description == payload.description
        and existing.category == payload.category
        and existing.amount_jod == payload.amount_jod
        and aware_utc(existing.incurred_at) == normalize_timestamp(payload.incurred_at)
        and existing.cost_view == payload.cost_view
    )


@router.post("/api/expenses", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
def create_expense(payload: ExpenseCreate, database: Session = Depends(get_db)) -> ExpenseResponse:
    season = owned_season(database, payload.crop_season_id)
    ensure_activity_date(season, payload.incurred_at)
    lookup = select(Expense).where(
        Expense.crop_season_id == payload.crop_season_id,
        Expense.idempotency_key == payload.idempotency_key,
    )
    return create_once(
        database, scope="canonical/expenses/" + payload.crop_season_id,
        key=payload.idempotency_key, payload=payload, lookup=lookup,
        same_payload=_same_payload, response=_response,
        build=lambda: Expense(
            id=str(uuid4()), crop_season_id=payload.crop_season_id,
            description=payload.description,
            category=payload.category, amount_jod=payload.amount_jod,
            incurred_at=normalize_timestamp(payload.incurred_at), cost_view=payload.cost_view,
            idempotency_key=payload.idempotency_key,
        ),
    )


@router.get("/api/farms/{farm_id}/expenses", response_model=list[ExpenseResponse])
def list_expenses(farm_id: str, database: Session = Depends(get_db)) -> list[ExpenseResponse]:
    owned_farm(database, farm_id)
    records = database.scalars(
        select(Expense)
        .join(CropSeason, Expense.crop_season_id == CropSeason.id)
        .join(Plot, CropSeason.plot_id == Plot.id)
        .join(Farm, Plot.farm_id == Farm.id)
        .where(Farm.id == farm_id)
        .order_by(Expense.incurred_at, Expense.id)
    ).all()
    return [_response(item) for item in records]
