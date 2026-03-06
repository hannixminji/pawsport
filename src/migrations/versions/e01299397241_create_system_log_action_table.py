"""create system_log_action table

Revision ID: e01299397241
Revises: 31e73d59feec
Create Date: 2026-03-06 13:31:58.483073

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e01299397241'
down_revision: Union[str, None] = '31e73d59feec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('system_action_log',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('actor_type', sa.String(), nullable=False),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('status', sa.Enum('SUCCESS', 'FAILURE', name='system_action_log_status_enum'), nullable=False),
    sa.Column('is_superuser', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_anonymous', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('actor_id', sa.Integer(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('actor_email', sa.String(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('role_ids', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text('NULL'), nullable=True),
    sa.Column('resource_type', sa.String(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('resource_id', sa.Text(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('error_code', sa.String(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('error_message', sa.Text(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('request_id', sa.String(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('ip_address', sa.String(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('user_agent', sa.Text(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('before_state', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text('NULL'), nullable=True),
    sa.Column('after_state', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text('NULL'), nullable=True),
    sa.Column('extra_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text('NULL'), nullable=True),
    sa.Column('duration_ms', sa.Integer(), server_default=sa.text('NULL'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_system_action_log_action_created_at', 'system_action_log', ['action', 'created_at'], unique=False)
    op.create_index('idx_system_action_log_actor_id_created_at', 'system_action_log', ['actor_id', 'created_at'], unique=False)
    op.create_index('idx_system_action_log_failures', 'system_action_log', ['status', 'created_at'], unique=False, postgresql_where=sa.text("status = 'FAILURE'"))
    op.create_index('idx_system_action_log_request_id', 'system_action_log', ['request_id'], unique=False)
    op.create_index('idx_system_action_log_resource_type_resource_id_created_at', 'system_action_log', ['resource_type', 'resource_id', 'created_at'], unique=False)
    op.create_index('idx_system_action_log_status_created_at', 'system_action_log', ['status', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_system_action_log_status_created_at', table_name='system_action_log')
    op.drop_index('idx_system_action_log_resource_type_resource_id_created_at', table_name='system_action_log')
    op.drop_index('idx_system_action_log_request_id', table_name='system_action_log')
    op.drop_index('idx_system_action_log_failures', table_name='system_action_log', postgresql_where=sa.text("status = 'FAILURE'"))
    op.drop_index('idx_system_action_log_actor_id_created_at', table_name='system_action_log')
    op.drop_index('idx_system_action_log_action_created_at', table_name='system_action_log')
    op.drop_table('system_action_log')
    op.execute("DROP TYPE IF EXISTS system_action_log_status_enum")
