"""Persist catalog progress between worker batches and restarts."""
from alembic import op
import sqlalchemy as sa

revision = "81a4f3c26b90"
down_revision = "f701c5b2d9a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("merchants", sa.Column("crawl_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade():
    op.drop_column("merchants", "crawl_state")
