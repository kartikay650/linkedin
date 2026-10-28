"""add drafts.original_text

drafts.text is not a record of what the tool generated: Tweak overwrites it and Regenerate deletes
the row. A reviewer pressing "No question" erased the question it fixed, so any question rate
measured off `text` undercounted by exactly the amount of work the reviewer put in — reported as
questions on "every second or third comment" while the table read 3%.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('drafts', sa.Column('original_text', sa.Text(), nullable=True))
    # Existing rows: text is the closest available approximation. Rows already tweaked are
    # unrecoverable, which is precisely why this column is being added.
    op.execute("update drafts set original_text = text where original_text is null")


def downgrade() -> None:
    op.drop_column('drafts', 'original_text')
