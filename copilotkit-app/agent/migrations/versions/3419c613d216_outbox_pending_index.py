"""Exclude permanently failed messages from the pending delivery index."""
from alembic import op
import sqlalchemy as sa

revision = "3419c613d216"
down_revision = "2ecd402462bc"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_outbox_pending", table_name="outbox", schema="research")
    op.create_index("ix_outbox_pending", "outbox", ["available_at"], schema="research",
                    postgresql_where=sa.text("delivered_at IS NULL AND failed_at IS NULL"))


def downgrade():
    op.drop_index("ix_outbox_pending", table_name="outbox", schema="research")
    op.create_index("ix_outbox_pending", "outbox", ["available_at"], schema="research",
                    postgresql_where=sa.text("delivered_at IS NULL"))
