"""add creator_clients.priority and posts.is_priority

Lara: "is there a way these accounts get priority inside our commenting tool to Joe, and then the
most second relevant account get selected for our second account to engage?"

creator_clients.priority marks a client as having first claim on a creator's posts.
posts.is_priority is stamped from it at scrape time, so the feed quota can rank on a plain column
instead of a correlated subquery, and so the change applies only to newly fetched posts.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('creator_clients',
                  sa.Column('priority', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('posts',
                  sa.Column('is_priority', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('posts', 'is_priority')
    op.drop_column('creator_clients', 'priority')
