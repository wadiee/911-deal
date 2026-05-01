"""add_scrape_events

Revision ID: c3e1d2a7f501
Revises: 8034207b7c67
Create Date: 2026-05-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'c3e1d2a7f501'
down_revision: Union[str, Sequence[str], None] = '8034207b7c67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scrape_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('run_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('restriction_signal', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_scrape_events_source', 'scrape_events', ['source'])
    op.create_index('ix_scrape_events_run_id', 'scrape_events', ['run_id'])
    op.create_index('ix_scrape_events_created_at', 'scrape_events', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_scrape_events_created_at', table_name='scrape_events')
    op.drop_index('ix_scrape_events_run_id', table_name='scrape_events')
    op.drop_index('ix_scrape_events_source', table_name='scrape_events')
    op.drop_table('scrape_events')
