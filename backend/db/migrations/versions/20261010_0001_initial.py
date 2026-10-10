"""Create the minimum farm, season, expense, and irrigation schema.

Revision ID: 20261010_0001
Revises: None
"""

from alembic import op
import sqlalchemy as sa


revision = "20261010_0001"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("preferred_language", sa.String(2), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("preferred_language IN ('ar', 'en')", name="ck_users_language"),
    )

    op.create_table(
        "farms",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("owner_id", sa.String(100), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_name", sa.String(200), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("timezone", sa.String(50), nullable=False),
        sa.Column("is_sample", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_farms_latitude"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_farms_longitude"),
        sa.CheckConstraint("timezone = 'Asia/Amman'", name="ck_farms_timezone"),
    )
    op.create_index("ix_farms_owner_id", "farms", ["owner_id"])

    op.create_table(
        "plots",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("farm_id", sa.String(100), sa.ForeignKey("farms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("area_m2", sa.Numeric(14, 3), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("area_m2 > 0", name="ck_plots_area_positive"),
    )
    op.create_index("ix_plots_farm_id", "plots", ["farm_id"])

    op.create_table(
        "crop_seasons",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("plot_id", sa.String(100), sa.ForeignKey("plots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crop", sa.String(50), nullable=False),
        sa.Column("establishment_date", sa.Date(), nullable=False),
        sa.Column("establishment_method", sa.String(30), nullable=False),
        sa.Column("crop_stage", sa.String(30), nullable=False),
        sa.Column("irrigation_method", sa.String(30), nullable=False),
        sa.Column("irrigation_efficiency", sa.Numeric(6, 5)),
        sa.Column("effective_rain_fraction", sa.Numeric(6, 5)),
        sa.Column("system_flow_liters_per_hour", sa.Numeric(14, 3)),
        sa.Column("expected_marketable_kg", sa.Numeric(14, 3)),
        sa.Column("assumed_sale_price_jod_per_kg", sa.Numeric(14, 4)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("crop = 'tomato'", name="ck_crop_seasons_crop"),
        sa.CheckConstraint("establishment_method IN ('transplanted', 'direct_seeded', 'unknown')", name="ck_crop_seasons_establishment_method"),
        sa.CheckConstraint("crop_stage IN ('initial', 'development', 'mid_season', 'late_season')", name="ck_crop_seasons_stage"),
        sa.CheckConstraint("irrigation_method = 'drip'", name="ck_crop_seasons_irrigation_method"),
        sa.CheckConstraint("irrigation_efficiency IS NULL OR (irrigation_efficiency > 0 AND irrigation_efficiency <= 1)", name="ck_crop_seasons_efficiency"),
        sa.CheckConstraint("effective_rain_fraction IS NULL OR (effective_rain_fraction >= 0 AND effective_rain_fraction <= 1)", name="ck_crop_seasons_rain_fraction"),
        sa.CheckConstraint("system_flow_liters_per_hour IS NULL OR system_flow_liters_per_hour > 0", name="ck_crop_seasons_flow"),
        sa.CheckConstraint("expected_marketable_kg IS NULL OR expected_marketable_kg >= 0", name="ck_crop_seasons_expected_harvest"),
        sa.CheckConstraint("assumed_sale_price_jod_per_kg IS NULL OR assumed_sale_price_jod_per_kg >= 0", name="ck_crop_seasons_sale_price"),
    )
    op.create_index("ix_crop_seasons_plot_id", "crop_seasons", ["plot_id"])

    op.create_table(
        "expenses",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("crop_season_id", sa.String(100), sa.ForeignKey("crop_seasons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("amount_jod", sa.Numeric(14, 3), nullable=False),
        sa.Column("incurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_view", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(150), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("amount_jod >= 0", name="ck_expenses_amount"),
        sa.CheckConstraint("cost_view IN ('cash', 'full')", name="ck_expenses_cost_view"),
        sa.UniqueConstraint("crop_season_id", "idempotency_key", name="uq_expenses_season_idempotency"),
    )
    op.create_index("ix_expenses_crop_season_id", "expenses", ["crop_season_id"])

    op.create_table(
        "irrigation_events",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("crop_season_id", sa.String(100), sa.ForeignKey("crop_seasons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount_liters", sa.Numeric(16, 3), nullable=False),
        sa.Column("duration_hours", sa.Numeric(10, 3)),
        sa.Column("system_flow_liters_per_hour", sa.Numeric(14, 3)),
        sa.Column("measurement_basis", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(150), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("amount_liters >= 0", name="ck_irrigation_amount"),
        sa.CheckConstraint("duration_hours IS NULL OR duration_hours > 0", name="ck_irrigation_duration"),
        sa.CheckConstraint("system_flow_liters_per_hour IS NULL OR system_flow_liters_per_hour > 0", name="ck_irrigation_flow"),
        sa.CheckConstraint("measurement_basis IN ('measured', 'calibrated', 'estimated', 'unknown')", name="ck_irrigation_measurement_basis"),
        sa.CheckConstraint("status = 'confirmed'", name="ck_irrigation_confirmed_only"),
        sa.UniqueConstraint("crop_season_id", "idempotency_key", name="uq_irrigation_season_idempotency"),
    )
    op.create_index("ix_irrigation_events_crop_season_id", "irrigation_events", ["crop_season_id"])


def downgrade() -> None:
    op.drop_table("irrigation_events")
    op.drop_table("expenses")
    op.drop_table("crop_seasons")
    op.drop_table("plots")
    op.drop_table("farms")
    op.drop_table("users")
