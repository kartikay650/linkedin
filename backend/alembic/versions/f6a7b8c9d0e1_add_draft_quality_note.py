"""add drafts.quality_note

A writing-quality warning surfaced on the draft card when the drafter could not fix a style
problem it detected — currently only the stacked-statement shape, where the comment is two or
more sentences with no comma and the regenerate came back the same way. The reviewer sees both
options with the weaker one labelled, rather than the tool silently shipping it as if it were fine
or refusing to return anything.

Kept out of drafts.provenance on purpose: that column is the clinical-safety trace, and
_flagged_claims() triggers strip_unverifiable() on any span marked "unverified" there.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('drafts', sa.Column('quality_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('drafts', 'quality_note')
