"""nullify_default_system_prompt

Revision ID: 7e490836d179
Revises: c1d2e3f4a5b6
Create Date: 2025-12-29 16:54:36.635574

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7e490836d179"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


# This is the default system prompt from the previous migration (87c52ec39f84)
# ruff: noqa: E501, W605 start
PREVIOUS_DEFAULT_SYSTEM_PROMPT = """
You are a highly capable, thoughtful, and precise assistant. Your goal is to deeply understand the user's intent, ask clarifying questions when needed, think step-by-step through complex problems, provide clear and accurate answers, and proactively anticipate helpful follow-up information. Always prioritize being truthful, nuanced, insightful, and efficient.

The current date is [[CURRENT_DATETIME]].[[CITATION_GUIDANCE]]

# Response Style
You use different text styles, bolding, emojis (sparingly), block quotes, and other formatting to make your responses more readable and engaging.
You use proper Markdown and LaTeX to format your responses for math, scientific, and chemical formulas, symbols, etc.: '$$\\n[expression]\\n$$' for standalone cases and '\\( [expression] \\)' when inline.
For code you prefer to use Markdown and specify the language.
You can use horizontal rules (---) to separate sections of your responses.
You can use Markdown tables to format your responses for data, lists, and other structured information.
""".lstrip()
# ruff: noqa: E501, W605 end


def upgrade() -> None:
    # Make system_prompt column nullable (model already has nullable=True but DB doesn't)
    op.alter_column(
        "persona",
        "system_prompt",
        nullable=True,
    )

    # Set system_prompt to NULL where it matches the previous default
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET system_prompt = NULL
            WHERE system_prompt = :previous_default
            """
        ),
        {"previous_default": PREVIOUS_DEFAULT_SYSTEM_PROMPT},
    )


def downgrade() -> None:
    # Restore the default system prompt for personas that have NULL
    # Note: This may restore the prompt to personas that originally had NULL
    # before this migration, but there's no way to distinguish them
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET system_prompt = :previous_default
            WHERE system_prompt IS NULL
            """
        ),
        {"previous_default": PREVIOUS_DEFAULT_SYSTEM_PROMPT},
    )

    # Revert system_prompt column to not nullable
    op.alter_column(
        "persona",
        "system_prompt",
        nullable=False,
    )
