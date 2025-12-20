"""add query_embeddings to chat_message and query_dependent_learnings table

Revision ID: e3f4a5b6c7d8
Revises: 12h73u00mcwb
Create Date: 2025-12-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e3f4a5b6c7d8"
down_revision = "12h73u00mcwb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column(
            "query_embeddings",
            postgresql.ARRAY(sa.Float()),
            nullable=True,
        ),
    )

    op.add_column(
        "research_agent_iteration_sub_step",
        sa.Column(
            "sub_step_tool_name",
            sa.String(),
            nullable=True,
        ),
    )

    # Create query_dependent_learnings table
    op.create_table(
        "query_dependent_learnings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("insight_text", sa.String(), nullable=False),
        sa.Column("insight_type", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create junction table for query_dependent_learnings and chat_message
    op.create_table(
        "query_dependent_learning__chat_message",
        sa.Column("learning_id", sa.Integer(), nullable=False),
        sa.Column("chat_message_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["learning_id"],
            ["query_dependent_learnings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chat_message_id"],
            ["chat_message.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("learning_id", "chat_message_id"),
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("query_dependent_learning__chat_message")
    op.drop_table("query_dependent_learnings")

    op.drop_column("chat_message", "query_embeddings")
    op.drop_column("research_agent_iteration_sub_step", "sub_step_tool_name")
