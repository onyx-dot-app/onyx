"""nullify_default_task_prompt

Revision ID: 699221885109
Revises: 7e490836d179
Create Date: 2025-12-30 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "699221885109"
down_revision = "7e490836d179"
branch_labels = None
depends_on = None

DEFAULT_PERSONA_ID = 0


def upgrade() -> None:
    # Make task_prompt column nullable
    # Note: The model had nullable=True but the DB column was NOT NULL until this point
    op.alter_column(
        "persona",
        "task_prompt",
        nullable=True,
    )

    # Set task_prompt to NULL for the default persona
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET task_prompt = NULL
            WHERE id = :persona_id
            """
        ),
        {"persona_id": DEFAULT_PERSONA_ID},
    )


def downgrade() -> None:
    # Restore task_prompt to empty string for the default persona
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET task_prompt = ''
            WHERE id = :persona_id AND task_prompt IS NULL
            """
        ),
        {"persona_id": DEFAULT_PERSONA_ID},
    )

    # Set any remaining NULL task_prompts to empty string before making non-nullable
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET task_prompt = ''
            WHERE task_prompt IS NULL
            """
        )
    )

    # Revert task_prompt column to not nullable
    op.alter_column(
        "persona",
        "task_prompt",
        nullable=False,
    )
