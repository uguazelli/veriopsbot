"""enable_rls

Revision ID: 0914bef95298
Revises: c8ae8a63604c
Create Date: 2026-01-14 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0914bef95298'
down_revision: Union[str, Sequence[str], None] = 'c8ae8a63604c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable RLS on tables
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY")

    # 2. Create Policy
    # We use current_setting(..., true) to return NULL if the variable is not set,
    # ensuring it fails closed (returns nothing) rather than crashing the app.
    # We cast to uuid because tenant_id is vector(uuid)? No it is uuid type.

    # Policy for documents
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON documents
        USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
    """)

    # Policy for chat_sessions
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON chat_sessions
        USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
    """)

    # Policy for chat_messages
    # Chat messages are owned by a session.
    # We can join to session, but RLS on joins can be tricky for performance.
    # However, chat_messages usually don't have tenant_id directly?
    # Let's check the schema from c8ae8a63604c_initial_schema.py

    # Checking schema memory:
    # documents -> tenant_id UUID
    # chat_sessions -> tenant_id UUID
    # chat_messages -> session_id UUID (NO tenant_id)

    # Ah, standard RLS needs the column on the table OR a subquery.
    # A subquery policy on chat_messages:
    # USING (session_id IN (SELECT id FROM chat_sessions WHERE tenant_id = current_setting('app.current_tenant', true)::uuid))

    op.execute("""
        CREATE POLICY tenant_isolation_policy ON chat_messages
        USING (
            session_id IN (
                SELECT id
                FROM chat_sessions
                WHERE tenant_id = current_setting('app.current_tenant', true)::uuid
            )
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON chat_messages")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON chat_sessions")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON documents")

    op.execute("ALTER TABLE chat_messages DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_sessions DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents DISABLE ROW LEVEL SECURITY")
