"""Relational records for farm operations; all money is stored in JOD."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id() -> str:
    return str(uuid.uuid4())


class Farm(Base):
    __tablename__ = "farms"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_farm_idempotency"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(240))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    irrigation_efficiency: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    effective_rain_fraction: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    area_dunum: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    planting_date: Mapped[date | None] = mapped_column(Date)
    crop_stage: Mapped[str | None] = mapped_column(String(40))
    irrigation_method: Mapped[str | None] = mapped_column(String(40))
    data_origin: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    seasons: Mapped[list[GrowingSeason]] = relationship(back_populates="farm", cascade="all, delete-orphan")
    irrigation_records: Mapped[list[IrrigationRecord]] = relationship(back_populates="farm", cascade="all, delete-orphan")
    expenses: Mapped[list[Expense]] = relationship(back_populates="farm", cascade="all, delete-orphan")
    harvests: Mapped[list[Harvest]] = relationship(back_populates="farm", cascade="all, delete-orphan")
    sales: Mapped[list[Sale]] = relationship(back_populates="farm", cascade="all, delete-orphan")


class GrowingSeason(Base):
    __tablename__ = "growing_seasons"
    __table_args__ = (
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="ck_season_dates"),
        UniqueConstraint("farm_id", "idempotency_key", name="uq_season_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    crop: Mapped[str] = mapped_column(String(80), nullable=False, default="tomato")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_harvest_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    projected_costs_jod: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    projected_revenue_jod: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    fertilizer_budget_jod: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    farm: Mapped[Farm] = relationship(back_populates="seasons")


class IdempotentRecord:
    """Mixin for safe create retries when clients supply Idempotency-Key."""
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class IrrigationRecord(IdempotentRecord, Base):
    __tablename__ = "irrigation_records"
    __table_args__ = (UniqueConstraint("farm_id", "idempotency_key", name="uq_irrigation_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True)
    season_id: Mapped[str | None] = mapped_column(ForeignKey("growing_seasons.id", ondelete="SET NULL"), index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    amount_mm: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    farm: Mapped[Farm] = relationship(back_populates="irrigation_records")


class Expense(IdempotentRecord, Base):
    __tablename__ = "expenses"
    __table_args__ = (
        UniqueConstraint("farm_id", "idempotency_key", name="uq_expense_idempotency"),
        CheckConstraint("amount_jod >= 0", name="ck_expense_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True)
    season_id: Mapped[str | None] = mapped_column(ForeignKey("growing_seasons.id", ondelete="SET NULL"), index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    amount_jod: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    farm: Mapped[Farm] = relationship(back_populates="expenses")


class Harvest(IdempotentRecord, Base):
    __tablename__ = "harvests"
    __table_args__ = (
        UniqueConstraint("farm_id", "idempotency_key", name="uq_harvest_idempotency"),
        CheckConstraint("quantity_kg > 0", name="ck_harvest_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True)
    season_id: Mapped[str | None] = mapped_column(ForeignKey("growing_seasons.id", ondelete="SET NULL"), index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    farm: Mapped[Farm] = relationship(back_populates="harvests")


class Sale(IdempotentRecord, Base):
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("farm_id", "idempotency_key", name="uq_sale_idempotency"),
        CheckConstraint("quantity_kg > 0", name="ck_sale_positive_quantity"),
        CheckConstraint("unit_price_jod >= 0", name="ck_sale_nonnegative_price"),
        Index("ix_sales_farm_date", "farm_id", "date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True)
    season_id: Mapped[str | None] = mapped_column(ForeignKey("growing_seasons.id", ondelete="SET NULL"), index=True)
    harvest_id: Mapped[str | None] = mapped_column(ForeignKey("harvests.id", ondelete="SET NULL"), index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price_jod: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    total_jod: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    buyer: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    farm: Mapped[Farm] = relationship(back_populates="sales")
