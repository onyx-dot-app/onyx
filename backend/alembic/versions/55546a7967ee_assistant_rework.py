"""assistant_rework

Revision ID: 55546a7967ee
Revises: 61ff3651add4
Create Date: 2024-09-18 17:00:23.755399

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "55546a7967ee"
down_revision = "61ff3651add4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reworking persona and user tables for new assistant features
    # keep track of user's chosen assistants separate from their `ordering`
    op.add_column("persona", sa.Column("builtin_persona", sa.Boolean(), nullable=True))
    op.execute("UPDATE persona SET builtin_persona = default_persona")
    op.alter_column("persona", "builtin_persona", nullable=False)
    op.drop_index("_default_persona_name_idx", table_name="persona")
    op.create_index(
        "_builtin_persona_name_idx",
        "persona",
        ["name"],
        unique=True,
        postgresql_where=sa.text("builtin_persona = true"),
    )

    op.add_column(
        "user", sa.Column("visible_assistants", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "user", sa.Column("hidden_assistants", postgresql.JSONB(), nullable=True)
    )
    op.execute(
        "UPDATE \"user\" SET visible_assistants = '[]'::jsonb, hidden_assistants = '[]'::jsonb"
    )
    op.alter_column(
        "user",
        "visible_assistants",
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    op.alter_column(
        "user",
        "hidden_assistants",
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    op.drop_column("persona", "default_persona")
    op.add_column(
        "persona", sa.Column("is_default_persona", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    # Reverting changes made in upgrade
    op.drop_column("user", "hidden_assistants")
    op.drop_column("user", "visible_assistants")
    op.drop_index("_builtin_persona_name_idx", table_name="persona")

    op.drop_column("persona", "is_default_persona")
    op.add_column("persona", sa.Column("default_persona", sa.Boolean(), nullable=True))
    op.execute("UPDATE persona SET default_persona = builtin_persona")
    op.alter_column("persona", "default_persona", nullable=False)
    op.drop_column("persona", "builtin_persona")
    op.create_index(
        "_default_persona_name_idx",
        "persona",
        ["name"],
        unique=True,
        postgresql_where=sa.text("default_persona = true"),
    )
