"""add burner proxy_session_id + fingerprint columns

Revision ID: a1b2c3d4e5f6
Revises: beb4d174daa8
Create Date: 2026-07-09 07:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'beb4d174daa8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('burners', sa.Column('proxy_session_id', sa.String(), nullable=True))
    op.add_column('burners', sa.Column('locale', sa.String(), nullable=True))
    op.add_column('burners', sa.Column('timezone_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('burners', 'timezone_id')
    op.drop_column('burners', 'locale')
    op.drop_column('burners', 'proxy_session_id')
