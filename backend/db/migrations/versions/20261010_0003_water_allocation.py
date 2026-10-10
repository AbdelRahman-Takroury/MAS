"""Add nullable season water allocation; existing farms remain unknown."""
from alembic import op
import sqlalchemy as sa

revision = '20261010_0003'
down_revision = '20261010_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('crop_seasons', sa.Column('water_available_liters', sa.Numeric(16, 3),
                  sa.CheckConstraint('water_available_liters >= 0', name='ck_season_water_nonnegative'), nullable=True))
    op.add_column('crop_seasons', sa.Column('water_period_start', sa.Date(), nullable=True))
    op.add_column('crop_seasons', sa.Column('water_period_end', sa.Date(), nullable=True))
    op.add_column('crop_seasons', sa.Column('water_allocation_is_demo', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    with op.batch_alter_table('crop_seasons') as batch:
        batch.drop_constraint('ck_season_water_nonnegative', type_='check')
        for name in ('water_allocation_is_demo', 'water_period_end', 'water_period_start', 'water_available_liters'):
            batch.drop_column(name)
