"""add posts.language

Several tracked creators post in German, French, Dutch, Spanish or Italian. Those posts reached the
engagement queue and the drafter wrote comments in that language, which no client will post.
Detection is deterministic (app/lang.py), so it costs nothing and could backfill the rows already
stored. Defaults to 'en' so nothing already in the queue disappears on deploy.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('posts',
                  sa.Column('language', sa.String(), nullable=False, server_default='en'))


def downgrade() -> None:
    op.drop_column('posts', 'language')
