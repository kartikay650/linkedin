"""add indexes for the per-post feed quota

The feed quota in routers/posts.py asks, for each row, how many other client feeds hold the same
post_url with a higher relevance score. Without an index on posts(post_url) that is a sequential
scan per row: measured 568ms across the table, against 22ms with the index.

drafts(post_id) was missing entirely, which also made every _WORKING / _DRAFTED / _APPROVED /
_POSTED exists() check seq-scan the drafts table. Those run on every feed read, every tab badge
and the notification summary, so this indexes an existing hot path as well as the new one.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_drafts_post_id', 'drafts', ['post_id'], unique=False)
    op.create_index('ix_posts_post_url', 'posts', ['post_url'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_posts_post_url', table_name='posts')
    op.drop_index('ix_drafts_post_id', table_name='drafts')
