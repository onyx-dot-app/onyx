"""agent to agent

Revision ID: 6c5e6b7fbbab
Revises: e8f0d2a38171
Create Date: 2025-12-05 10:56:43.190279

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6c5e6b7fbbab"
down_revision = "e8f0d2a38171"
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
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "pass_files",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("max_tokens_to_child", sa.Integer(), nullable=True),
        sa.Column("max_tokens_from_child", sa.Integer(), nullable=True),
        sa.Column("invocation_instructions", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_persona_id"],
            ["persona.id"],
            ondelete="CASCADE",
            name="fk_persona__persona_parent_persona_id_persona",
        ),
        sa.ForeignKeyConstraint(
            ["child_persona_id"],
            ["persona.id"],
            ondelete="CASCADE",
            name="fk_persona__persona_child_persona_id_persona",
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
