"""seed_load_skill_tool

Revision ID: d1bba4465bb7
Revises: dfe0f30fd0ce
Create Date: 2026-06-16 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d1bba4465bb7"
down_revision = "dfe0f30fd0ce"
branch_labels = None
depends_on = None


LOAD_SKILL_TOOL = {
    "name": "LoadSkillTool",
    "display_name": "Load Skill",
    "description": (
        "Load the full instructions for one of this assistant's attached "
        "skills, identified by its slug."
    ),
    "in_code_tool_id": "LoadSkillTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()

    existing = conn.execute(
        sa.text(
            "SELECT in_code_tool_id FROM tool WHERE in_code_tool_id = :in_code_tool_id"
        ),
        {"in_code_tool_id": LOAD_SKILL_TOOL["in_code_tool_id"]},
    ).fetchone()

    if existing:
        conn.execute(
            sa.text("""
                UPDATE tool
                SET name = :name,
                    display_name = :display_name,
                    description = :description
                WHERE in_code_tool_id = :in_code_tool_id
                """),
            LOAD_SKILL_TOOL,
        )
    else:
        conn.execute(
            sa.text("""
                INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
                VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
                """),
            LOAD_SKILL_TOOL,
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": LOAD_SKILL_TOOL["in_code_tool_id"]},
    )
