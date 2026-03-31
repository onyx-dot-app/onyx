"""csv to tabular chat file type

Revision ID: 8188861f4e92
Revises: 1d78c0ca7853
Create Date: 2026-03-31 19:23:05.753184

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "8188861f4e92"
down_revision = "1d78c0ca7853"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE chat_message
        SET files = (
            SELECT jsonb_agg(
                CASE
                    WHEN elem->>'type' = 'csv'
                    THEN jsonb_set(elem, '{type}', '"tabular"')
                    ELSE elem
                END
            )
            FROM jsonb_array_elements(files) AS elem
        )
        WHERE files::text LIKE '%"type": "csv"%'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE chat_message
        SET files = (
            SELECT jsonb_agg(
                CASE
                    WHEN elem->>'type' = 'tabular'
                    THEN jsonb_set(elem, '{type}', '"csv"')
                    ELSE elem
                END
            )
            FROM jsonb_array_elements(files) AS elem
        )
        WHERE files::text LIKE '%"type": "tabular"%'
        """
    )
