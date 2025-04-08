"""server default chosen assistants

Revision ID: 35e6853a51d5
Revises: c99d76fcd298
Create Date: 2024-09-13 13:20:32.885317

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "35e6853a51d5"
down_revision = "c99d76fcd298"
branch_labels = None
depends_on = None

DEFAULT_ASSISTANTS = [-2, -1, 0]


def upgrade() -> None:
    # Step 1: Update any NULL values to the default value
    # This upgrades existing users without ordered assistant
    # to have default assistants set to visible assistants which are
    # accessible by them.
    op.execute(
        """
        UPDATE "user" u
        SET chosen_assistants = (
            SELECT jsonb_agg(
                p.id ORDER BY
                    COALESCE(p.display_priority, 2147483647) ASC,
                    p.id ASC
            )
            FROM persona p
            LEFT JOIN persona__user pu ON p.id = pu.persona_id AND pu.user_id = u.id
            WHERE p.is_visible = true
            AND (p.is_public = true OR pu.user_id IS NOT NULL)
        )
        WHERE chosen_assistants IS NULL
        OR chosen_assistants = 'null'
        OR jsonb_typeof(chosen_assistants) = 'null'
        OR (jsonb_typeof(chosen_assistants) = 'string' AND chosen_assistants = '"null"')
    """
    )

    # Step 2: Alter the column to make it non-nullable
    op.alter_column(
        "user",
        "chosen_assistants",
        type_=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text(f"'{DEFAULT_ASSISTANTS}'::jsonb"),
    )


def downgrade() -> None:
    op.alter_column(
        "user",
        "chosen_assistants",
        type_=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        server_default=None,
    )
