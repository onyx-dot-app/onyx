"""add research agent database tables and chat message research fields

Revision ID: 5ae8240accb3
Revises: 62c3a055a141
Create Date: 2025-08-06 14:29:24.691388

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "5ae8240accb3"
down_revision = "62c3a055a141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add research_type and research_plan columns to chat_message table
    op.add_column(
        "chat_message",
        sa.Column("research_type", sa.String(), nullable=True),
    )
    op.add_column(
        "chat_message",
        sa.Column("research_plan", postgresql.JSONB(), nullable=True),
    )

    # Create research_agent_iteration table
    op.create_table(
        "research_agent_iteration",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "primary_question_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("iteration_nr", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=True),
        sa.Column("reasoning", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create research_agent_iteration_sub_step table
    op.create_table(
        "research_agent_iteration_sub_step",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "primary_question_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_question_id",
            sa.Integer(),
            sa.ForeignKey("research_agent_iteration_sub_step.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("iteration_nr", sa.Integer(), nullable=False),
        sa.Column("iteration_sub_step_nr", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sub_step_instructions", sa.String(), nullable=True),
        sa.Column(
            "sub_step_tool_id",
            sa.Integer(),
            sa.ForeignKey("tool.id"),
            nullable=True,
        ),
        sa.Column("reasoning", sa.String(), nullable=True),
        sa.Column("sub_answer", sa.String(), nullable=True),
        sa.Column("cited_doc_results", postgresql.JSONB(), nullable=True),
        sa.Column("claims", postgresql.JSONB(), nullable=True),
        sa.Column("additional_data", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("research_agent_iteration_sub_step")
    op.drop_table("research_agent_iteration")

    # Remove columns from chat_message table
    op.drop_column("chat_message", "research_plan")
    op.drop_column("chat_message", "research_type")
