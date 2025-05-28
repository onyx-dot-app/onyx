"""remove description from starter messages

Revision ID: b72ed7a5db0e
Revises: 33cb72ea4d80
Create Date: 2024-11-03 15:55:28.944408

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b72ed7a5db0e"
down_revision = "33cb72ea4d80"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE persona
            SET starter_messages = (
                SELECT jsonb_agg(elem - 'description')
                FROM jsonb_array_elements(starter_messages) elem
            )
            WHERE starter_messages IS NOT NULL
              AND jsonb_typeof(starter_messages) = 'array'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE persona
            SET starter_messages = (
                SELECT jsonb_agg(elem || '{"description": ""}')
                FROM jsonb_array_elements(starter_messages) elem
            )
            WHERE starter_messages IS NOT NULL
              AND jsonb_typeof(starter_messages) = 'array'
            """
        )
    )
