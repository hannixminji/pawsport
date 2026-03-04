"""merge multiple heads

Revision ID: 6e478e860d70
Revises: b36594f7ead0
Create Date: 2026-03-04 10:55:22.443697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e478e860d70'
down_revision: Union[str, None] = 'b36594f7ead0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
