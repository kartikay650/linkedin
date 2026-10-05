"""add clients.archived

Stand a client down without destroying their data. The foreign keys from posts, client_documents,
watch_creators and prospects to clients are all NO ACTION, so deleting a client means deleting
their posts and drafts first — and if they return, the voice profile and creator assignments have
to be rebuilt from scratch. Archived clients are hidden from the dashboard sidebar; everything
they own stays queryable.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients',
                  sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('clients', 'archived')
