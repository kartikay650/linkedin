"""add drafts.source and drafts.provenance_hash

source: 'generated' (default, every existing row) or 'manual' for a comment a reviewer wrote with
"Write my own". provenance_hash: sha1 of the text the fact-check ran on, so an edited comment can
show that its check is stale. Both are small; adding a defaulted column is metadata-only in
Postgres 11+.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('drafts', sa.Column('source', sa.String(length=16), nullable=False,
                                      server_default='generated'))
    op.create_check_constraint('ck_drafts_source', 'drafts', "source in ('generated', 'manual')")
    op.add_column('drafts', sa.Column('provenance_hash', sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column('drafts', 'provenance_hash')
    op.drop_constraint('ck_drafts_source', 'drafts', type_='check')
    op.drop_column('drafts', 'source')
