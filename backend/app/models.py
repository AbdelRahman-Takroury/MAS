"""Minimum persistent domain model for the hackathon demonstration."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    preferred_language: Mapped[str] = mapped_column(String(2), default="ar", nullable=False)

    farms: Mapped[list["Farm"]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("preferred_language IN ('ar', 'en')", name="ck_users_language"),
    )


class Farm(TimestampMixin, Base):
    __tablename__ = "farms"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    location_name: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Amman", nullable=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    owner: Mapped[User] = relationship(back_populates="farms")
    plots: Mapped[list["Plot"]] = relationship(back_populates="farm", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_farms_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_farms_longitude"),
        CheckConstraint("timezone = 'Asia/Amman'", name="ck_farms_timezone"),
    )


class Plot(TimestampMixin, Base):
    __tablename__ = "plots"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)

    farm: Mapped[Farm] = relationship(back_populates="plots")
    crop_seasons: Mapped[list["CropSeason"]] = relationship(
        back_populates="plot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("area_m2 > 0", name="ck_plots_area_positive"),
    )


class CropSeason(TimestampMixin, Base):
    __tablename__ = "crop_seasons"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    plot_id: Mapped[str] = mapped_column(ForeignKey("plots.id", ondelete="CASCADE"), index=True)
    crop: Mapped[str] = mapped_column(String(50), nullable=False)
    establishment_date: Mapped[date] = mapped_column(Date, nullable=False)
    establishment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    crop_stage: Mapped[str] = mapped_column(String(30), nullable=False)
    irrigation_method: Mapped[str] = mapped_column(String(30), nullable=False)
    irrigation_efficiency: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    effective_rain_fraction: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    system_flow_liters_per_hour: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    expected_marketable_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    assumed_sale_price_jod_per_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    plot: Mapped[Plot] = relationship(back_populates="crop_seasons")
    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="crop_season", cascade="all, delete-orphan"
    )
    irrigation_events: Mapped[list["IrrigationEvent"]] = relationship(
        back_populates="crop_season", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("crop = 'tomato'", name="ck_crop_seasons_crop"),
        CheckConstraint(
            "establishment_method IN ('transplanted', 'direct_seeded', 'unknown')",
            name="ck_crop_seasons_establishment_method",
        ),
        CheckConstraint(
            "crop_stage IN ('initial', 'development', 'mid_season', 'late_season')",
            name="ck_crop_seasons_stage",
        ),
        CheckConstraint("irrigation_method = 'drip'", name="ck_crop_seasons_irrigation_method"),
        CheckConstraint(
            "irrigation_efficiency IS NULL OR (irrigation_efficiency > 0 AND irrigation_efficiency <= 1)",
            name="ck_crop_seasons_efficiency",
        ),
        CheckConstraint(
            "effective_rain_fraction IS NULL OR (effective_rain_fraction >= 0 AND effective_rain_fraction <= 1)",
            name="ck_crop_seasons_rain_fraction",
        ),
        CheckConstraint(
            "system_flow_liters_per_hour IS NULL OR system_flow_liters_per_hour > 0",
            name="ck_crop_seasons_flow",
        ),
        CheckConstraint(
            "expected_marketable_kg IS NULL OR expected_marketable_kg >= 0",
            name="ck_crop_seasons_expected_harvest",
        ),
        CheckConstraint(
            "assumed_sale_price_jod_per_kg IS NULL OR assumed_sale_price_jod_per_kg >= 0",
            name="ck_crop_seasons_sale_price",
        ),
    )


class Expense(TimestampMixin, Base):
    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    crop_season_id: Mapped[str] = mapped_column(
        ForeignKey("crop_seasons.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    amount_jod: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    incurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cost_view: Mapped[str] = mapped_column(String(20), default="cash", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(150), nullable=False)

    crop_season: Mapped[CropSeason] = relationship(back_populates="expenses")

    __table_args__ = (
        UniqueConstraint("crop_season_id", "idempotency_key", name="uq_expenses_season_idempotency"),
        CheckConstraint("amount_jod >= 0", name="ck_expenses_amount"),
        CheckConstraint("cost_view IN ('cash', 'full')", name="ck_expenses_cost_view"),
    )


class IrrigationEvent(TimestampMixin, Base):
    __tablename__ = "irrigation_events"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    crop_season_id: Mapped[str] = mapped_column(
        ForeignKey("crop_seasons.id", ondelete="CASCADE"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_liters: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    duration_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    system_flow_liters_per_hour: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    measurement_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="confirmed", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(150), nullable=False)

    crop_season: Mapped[CropSeason] = relationship(back_populates="irrigation_events")

    __table_args__ = (
        UniqueConstraint(
            "crop_season_id", "idempotency_key", name="uq_irrigation_season_idempotency"
        ),
        CheckConstraint("amount_liters >= 0", name="ck_irrigation_amount"),
        CheckConstraint(
            "duration_hours IS NULL OR duration_hours > 0", name="ck_irrigation_duration"
        ),
        CheckConstraint(
            "system_flow_liters_per_hour IS NULL OR system_flow_liters_per_hour > 0",
            name="ck_irrigation_flow",
        ),
        CheckConstraint(
            "measurement_basis IN ('measured', 'calibrated', 'estimated', 'unknown')",
            name="ck_irrigation_measurement_basis",
        ),
        CheckConstraint("status = 'confirmed'", name="ck_irrigation_confirmed_only"),
    )
