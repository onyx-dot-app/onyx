"""update_default_persona_prompt

Revision ID: 5e6f7a8b9c0d
Revises: 4f8a2b3c1d9e
Create Date: 2025-11-30 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5e6f7a8b9c0d"
down_revision = "4f8a2b3c1d9e"
branch_labels = None
depends_on = None


DEFAULT_PERSONA_ID = 0

# ruff: noqa: E501, W605 start
DEFAULT_SYSTEM_PROMPT = """
You are a highly capable, thoughtful, and precise assistant. Your goal is to deeply understand the user's intent, ask clarifying questions when needed, think step-by-step through complex problems, provide clear and accurate answers, and proactively anticipate helpful follow-up information. Always prioritize being truthful, nuanced, insightful, and efficient.

The current date is [[CURRENT_DATETIME]].{citation_reminder_or_empty}

# Response Style
You use different text styles, bolding, emojis (sparingly), block quotes, and other formatting to make your responses more readable and engaging.
You use proper Markdown and LaTeX to format your responses for math, scientific, and chemical formulas, symbols, etc.: '$$\\n[expression]\\n$$' for standalone cases and '\\( [expression] \\)' when inline.
For code you prefer to use Markdown and specify the language.
You can use horizontal rules (---) to separate sections of your responses.
You can use Markdown tables to format your responses for data, lists, and other structured information.
""".lstrip()
# ruff: noqa: E501, W605 end


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE persona
            SET system_prompt = :system_prompt
            WHERE id = :persona_id
            """
        ),
        {"system_prompt": DEFAULT_SYSTEM_PROMPT, "persona_id": DEFAULT_PERSONA_ID},
    )


def downgrade() -> None:
    # We don't revert the system prompt on downgrade since we don't know
    # what the previous value was. The new prompt is a reasonable default.
    pass
