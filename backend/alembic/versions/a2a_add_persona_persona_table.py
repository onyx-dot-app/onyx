"""add persona_persona table for agent-to-agent communication

Revision ID: a2a_persona_persona
Revises: f71470ba9274
Create Date: 2024-12-04

"""

from alembic import op
import sqlalchemy as sa

revision = "a2a_persona_persona"
down_revision = "f71470ba9274"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persona__persona",
        sa.Column("parent_persona_id", sa.Integer(), nullable=False),
        sa.Column("child_persona_id", sa.Integer(), nullable=False),
        sa.Column(
            "pass_conversation_context",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("pass_files", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("max_tokens_to_child", sa.Integer(), nullable=True),
        sa.Column("max_tokens_from_child", sa.Integer(), nullable=True),
        sa.Column("invocation_instructions", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_persona_id"],
            ["persona.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["child_persona_id"],
            ["persona.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("parent_persona_id", "child_persona_id"),
    )

    op.add_column(
        "tool_call",
        sa.Column("invoked_persona_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tool_call_invoked_persona",
        "tool_call",
        "persona",
        ["invoked_persona_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tool_call_invoked_persona", "tool_call", type_="foreignkey")
    op.drop_column("tool_call", "invoked_persona_id")
    op.drop_table("persona__persona")
