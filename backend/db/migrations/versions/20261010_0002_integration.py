"""Add dashboard planning fields and harvest/sale ledgers without replacing records."""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0002"
down_revision = "20261010_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("farms", sa.Column("name", sa.String(200)))
    for column in [sa.Column("name", sa.String(120)), sa.Column("end_date", sa.Date()),
                   sa.Column("projected_costs_jod", sa.Numeric(14, 3)),
                   sa.Column("fertilizer_budget_jod", sa.Numeric(14, 3))]:
        op.add_column("crop_seasons", column)
    op.add_column("irrigation_events", sa.Column("notes", sa.String(4000)))
    # Reuse the additive tables' metadata; never create/drop existing domain tables.
    from backend.app.models import Harvest, Sale, WriteReceipt
    for table in (Harvest.__table__, Sale.__table__, WriteReceipt.__table__):
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    for name in ("write_receipts", "sales", "harvests"):
        op.drop_table(name)
    op.drop_column("irrigation_events", "notes")
    for name in ("fertilizer_budget_jod", "projected_costs_jod", "end_date", "name"):
        op.drop_column("crop_seasons", name)
    op.drop_column("farms", "name")
