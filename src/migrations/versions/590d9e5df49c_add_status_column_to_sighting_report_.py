"""add status column to sighting_report, add sighting_report_status_enum with sighted and fostered, remove fostered from missing_report_status_enum

Revision ID: 590d9e5df49c
Revises: 7bf51f938393
Create Date: 2026-03-11 11:20:51.498052

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '590d9e5df49c'
down_revision: Union[str, None] = '7bf51f938393'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE sighting_report_status_enum AS ENUM ('sighted', 'fostered')")
    op.add_column('sighting_report', sa.Column('report_status', sa.Enum('sighted', 'fostered', name='sighting_report_status_enum'), server_default=sa.text("'sighted'::sighting_report_status_enum"), nullable=False))
    op.create_index('idx_sighting_report_status_active', 'sighting_report', ['report_status'], unique=False, postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('idx_sighting_report_status_active', table_name='sighting_report', postgresql_where=sa.text('is_deleted = false'))
    op.drop_column('sighting_report', 'report_status')
    op.execute("DROP TYPE sighting_report_status_enum")
