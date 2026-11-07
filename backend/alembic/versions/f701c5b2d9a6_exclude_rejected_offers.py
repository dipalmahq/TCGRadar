"""Retain rejected imports for history, exclude them from radar and alerts.

Revision ID: f701c5b2d9a6
Revises: c58f19d2a4b1
"""
from alembic import op
import sqlalchemy as sa

revision = "f701c5b2d9a6"
down_revision = "c58f19d2a4b1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("offers", sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("offers", "excluded")
