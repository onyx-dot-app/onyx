"""delete non-search assistants

Revision ID: f5437cc136c5
Revises: eaa3b5593925
Create Date: 2025-02-04 16:17:15.677256

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "f5437cc136c5"
down_revision = "eaa3b5593925"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    # Fix: split the statements into multiple op.execute() calls
    op.execute(
        """
        WITH personas_without_search AS (
            SELECT p.id
            FROM persona p
            LEFT JOIN persona__tool pt ON p.id = pt.persona_id
            LEFT JOIN tool t ON pt.tool_id = t.id
            GROUP BY p.id
            HAVING COUNT(CASE WHEN t.in_code_tool_id = 'run_search' THEN 1 END) = 0
        )
        UPDATE slack_channel_config
        SET persona_id = NULL
        WHERE is_default = TRUE AND persona_id IN (SELECT id FROM personas_without_search)
        """
    )

    op.execute(
        """
        WITH personas_without_search AS (
            SELECT p.id
            FROM persona p
            LEFT JOIN persona__tool pt ON p.id = pt.persona_id
            LEFT JOIN tool t ON pt.tool_id = t.id
            GROUP BY p.id
            HAVING COUNT(CASE WHEN t.in_code_tool_id = 'run_search' THEN 1 END) = 0
        )
        DELETE FROM slack_channel_config
        WHERE is_default = FALSE AND persona_id IN (SELECT id FROM personas_without_search)
        """
    )
