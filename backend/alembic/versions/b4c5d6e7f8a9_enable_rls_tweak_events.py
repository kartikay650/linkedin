"""enable row-level security on tweak_events

Supabase security advisor, 22 Nov 2026 (rls_disabled_in_public): tweak_events was the only table in
`public` without RLS, so anyone holding the project's anon key could read, edit and delete it
through the Data API. Every other table here already has RLS on and no policies, which denies the
anon and authenticated roles everything. The backend connects as `postgres`, which bypasses RLS,
so the app is unaffected. The dashboard uses Supabase only for login.

Any new table in `public` needs the same line in its own migration.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE public.tweak_events ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE public.tweak_events DISABLE ROW LEVEL SECURITY')
