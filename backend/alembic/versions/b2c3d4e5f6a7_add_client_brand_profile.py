"""add structured brand-profile fields to clients

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-09 08:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS = ["voice_guide", "viewpoints", "audience", "key_messages", "cta_rules", "guardrails"]


def upgrade() -> None:
    for c in _COLS:
        op.add_column('clients', sa.Column(c, sa.Text(), nullable=True))


def downgrade() -> None:
    for c in reversed(_COLS):
        op.drop_column('clients', c)
