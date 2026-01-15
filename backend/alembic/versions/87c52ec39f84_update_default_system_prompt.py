"""update_default_system_prompt

Revision ID: 87c52ec39f84
Revises: 7bd55f264e1b
Create Date: 2025-12-05 15:54:06.002452

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "87c52ec39f84"
down_revision = "7bd55f264e1b"
branch_labels = None
depends_on = None


DEFAULT_PERSONA_ID = 0

# ruff: noqa: E501, W605 start
DEFAULT_SYSTEM_PROMPT = """
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
