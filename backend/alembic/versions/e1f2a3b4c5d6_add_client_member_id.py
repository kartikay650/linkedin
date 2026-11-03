"""add clients.linkedin_member_id

Own-post exclusion matched LinkedIn handles only. Eric Verdin changed handle and 17 of his own posts
reached his feed, one with drafts pending. The member ID survives a rename. Backfilled from posts
authored under each client's handle (7 clients resolved unambiguously).

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('linkedin_member_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('clients', 'linkedin_member_id')
