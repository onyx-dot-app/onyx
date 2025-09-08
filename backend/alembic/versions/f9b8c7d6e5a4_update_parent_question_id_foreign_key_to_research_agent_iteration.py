"""remove foreign key constraints from research_agent_iteration_sub_step

Revision ID: f9b8c7d6e5a4
Revises: bd7c3bf8beba
Create Date: 2025-01-27 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f9b8c7d6e5a4"
down_revision = "bd7c3bf8beba"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing foreign key constraint for parent_question_id
    op.drop_constraint(
        "research_agent_iteration_sub_step_parent_question_id_fkey",
        "research_agent_iteration_sub_step",
        type_="foreignkey",
    )

    # Drop the parent_question_id column entirely
    op.drop_column("research_agent_iteration_sub_step", "parent_question_id")

    # Drop the foreign key constraint for primary_question_id to chat_message.id
    # (keep the column as it's needed for the composite foreign key)
    op.drop_constraint(
        "research_agent_iteration_sub_step_primary_question_id_fkey",
        "research_agent_iteration_sub_step",
        type_="foreignkey",
    )


def downgrade() -> None:
    # Restore the foreign key constraint for primary_question_id to chat_message.id
    op.create_foreign_key(
        "research_agent_iteration_sub_step_primary_question_id_fkey",
        "research_agent_iteration_sub_step",
        "chat_message",
        ["primary_question_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add back the parent_question_id column
    op.add_column(
        "research_agent_iteration_sub_step",
        sa.Column(
            "parent_question_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    # Restore the foreign key constraint pointing to research_agent_iteration_sub_step.id
    op.create_foreign_key(
        "research_agent_iteration_sub_step_parent_question_id_fkey",
        "research_agent_iteration_sub_step",
        "research_agent_iteration_sub_step",
        ["parent_question_id"],
        ["id"],
        ondelete="CASCADE",
    )
