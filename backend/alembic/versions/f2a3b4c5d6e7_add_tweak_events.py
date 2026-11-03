"""add tweak_events

A log of every Tweak chip press, free-text Tweak and "Different angle", with the text the reviewer
moved away from. No foreign keys, so it survives Regenerate deleting drafts. A few hundred short
rows a month.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tweak_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('client_id', sa.Integer(), nullable=True),
        sa.Column('post_id', sa.Integer(), nullable=True),
        sa.Column('draft_id', sa.Integer(), nullable=True),
        sa.Column('chip', sa.String(length=32), nullable=True),
        sa.Column('instruction', sa.Text(), nullable=True),
        sa.Column('before_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )
    op.create_index('ix_tweak_events_client_id', 'tweak_events', ['client_id'])


def downgrade() -> None:
    op.drop_index('ix_tweak_events_client_id', table_name='tweak_events')
    op.drop_table('tweak_events')
