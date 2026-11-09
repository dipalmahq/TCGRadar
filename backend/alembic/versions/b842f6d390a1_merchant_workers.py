"""Separate stock/watch schedules and merchant worker heartbeat."""
from alembic import op
import sqlalchemy as sa

revision = 'b842f6d390a1'
down_revision = '81a4f3c26b90'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('source_ready_at', 'worker_heartbeat_at', 'watch_requested_at'):
        op.add_column('merchants', sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column('offers', sa.Column('stock_attempted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('offers', sa.Column('next_stock_check_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('watch_targets', sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('watch_targets', sa.Column('next_check_at', sa.DateTime(timezone=True), nullable=True))
    # Preserve real observation times. Scheduling the backlog now does not make
    # any stock observation newer or change its availability.
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("UPDATE offers SET next_stock_check_at = CASE WHEN source_error IS NOT NULL THEN CURRENT_TIMESTAMP ELSE last_seen_at + INTERVAL '30 minutes' END")
        op.execute("UPDATE watch_targets SET next_check_at = COALESCE(last_checked_at + INTERVAL '5 minutes', CURRENT_TIMESTAMP)")
    else:
        op.execute("UPDATE offers SET next_stock_check_at = CASE WHEN source_error IS NOT NULL THEN CURRENT_TIMESTAMP ELSE datetime(last_seen_at, '+30 minutes') END")
        op.execute("UPDATE watch_targets SET next_check_at = COALESCE(datetime(last_checked_at, '+5 minutes'), CURRENT_TIMESTAMP)")
    op.create_index('ix_offers_next_stock_check_at', 'offers', ['next_stock_check_at'])
    op.create_index('ix_watch_targets_next_check_at', 'watch_targets', ['next_check_at'])
    for table, column in (('offers', 'next_stock_check_at'), ('watch_targets', 'next_check_at')):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade():
    op.drop_index('ix_watch_targets_next_check_at', table_name='watch_targets')
    op.drop_index('ix_offers_next_stock_check_at', table_name='offers')
    for name in ('last_attempt_at', 'next_check_at'):
        op.drop_column('watch_targets', name)
    for name in ('stock_attempted_at', 'next_stock_check_at'):
        op.drop_column('offers', name)
    for name in ('source_ready_at', 'worker_heartbeat_at', 'watch_requested_at'):
        op.drop_column('merchants', name)
