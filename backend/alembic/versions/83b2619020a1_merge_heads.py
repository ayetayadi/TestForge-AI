"""merge_heads

Revision ID: 83b2619020a1
Revises: i7d8e9f0a1b2, ac79303ad538
Create Date: 2026-05-20 12:40:30.232477

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83b2619020a1'
down_revision: Union[str, Sequence[str], None] = ('i7d8e9f0a1b2', 'ac79303ad538')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
