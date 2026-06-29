"""chat improvements: last_seen, reply_to

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen", sa.DateTime(), nullable=True))
    op.add_column("messages", sa.Column("reply_to_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "reply_to_id")
    op.drop_column("users", "last_seen")
