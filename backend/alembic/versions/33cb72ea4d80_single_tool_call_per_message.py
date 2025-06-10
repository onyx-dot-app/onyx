"""single tool call per message

Revision ID: 33cb72ea4d80
Revises: 5b29123cd710
Create Date: 2024-11-01 12:51:01.535003

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "33cb72ea4d80"
down_revision = "5b29123cd710"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Delete extraneous ToolCall entries
    # Keep only the ToolCall with the smallest 'id' for each 'message_id'
    op.execute(
        sa.text(
            """
            DELETE FROM tool_call
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM tool_call
                WHERE message_id IS NOT NULL
                GROUP BY message_id
            );
        """
        )
    )

    # Step 2: Add a unique constraint on message_id
    op.create_unique_constraint(
        constraint_name="uq_tool_call_message_id",
        table_name="tool_call",
        columns=["message_id"],
    )


def downgrade() -> None:
    # Step 1: Drop the unique constraint on message_id
    op.drop_constraint(
        constraint_name="uq_tool_call_message_id",
        table_name="tool_call",
        type_="unique",
    )
