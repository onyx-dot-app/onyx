"""Seed the main chat Skill reader.

Revision ID: 7b3f24d8a901
Revises: a604d04ad21b
"""

from alembic import op
import sqlalchemy as sa

revision = "7b3f24d8a901"
down_revision = "a604d04ad21b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A fixed ID makes tenant template clones and fresh migrations agree.
    op.execute(
        sa.text("""
        INSERT INTO tool (id, name, display_name, description, in_code_tool_id, enabled, passthrough_auth)
        VALUES (2000000001, 'read_skill', 'Skills',
                'Discover enabled Skills and read their Markdown without a sandbox.',
                'SkillTool', true, false)
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO persona__tool (persona_id, tool_id)
        SELECT 0, 2000000001 WHERE EXISTS (SELECT 1 FROM persona WHERE id = 0)
    """)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM persona__tool WHERE tool_id = 2000000001"))
    op.execute(
        sa.text(
            "DELETE FROM tool WHERE id = 2000000001 AND in_code_tool_id = 'SkillTool'"
        )
    )
