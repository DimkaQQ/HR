"""group chat type

Revision ID: 0004
Revises: 0003
Create Date: 2024-01-04

"""
from typing import Sequence, Union
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE conversationtype ADD VALUE IF NOT EXISTS 'group'")


def downgrade() -> None:
    pass  # PostgreSQL does not support removing enum values
