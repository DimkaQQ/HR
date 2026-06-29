"""gamification: xp, streak, last_active on users

Revision ID: 0003
Revises: 0002
Create Date: 2024-01-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("xp", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("last_active", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_active")
    op.drop_column("users", "streak_days")
    op.drop_column("users", "xp")
