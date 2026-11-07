"""Multiple selections in watch rules, retaining legacy single filters.

Revision ID: c58f19d2a4b1
Revises: 5063cdaab2ab
"""
from alembic import op
import sqlalchemy as sa

revision = "c58f19d2a4b1"
down_revision = "5063cdaab2ab"
branch_labels = None
depends_on = None


def upgrade():
    for field in ("game_ids", "merchant_ids", "set_codes", "languages", "product_types"):
        op.add_column("search_rules", sa.Column(field, sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade():
    for field in ("product_types", "languages", "set_codes", "merchant_ids", "game_ids"):
        op.drop_column("search_rules", field)
