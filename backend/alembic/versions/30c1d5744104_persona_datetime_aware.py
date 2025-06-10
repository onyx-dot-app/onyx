"""Persona Datetime Aware

Revision ID: 30c1d5744104
Revises: 7f99be1cb9f5
Create Date: 2023-10-16 23:21:01.283424

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "30c1d5744104"
down_revision = "7f99be1cb9f5"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("persona", sa.Column("datetime_aware", sa.Boolean(), nullable=True))
    op.execute("UPDATE persona SET datetime_aware = TRUE")
    op.alter_column("persona", "datetime_aware", nullable=False)
    op.create_index(
        "_default_persona_name_idx",
        "persona",
        ["name"],
        unique=True,
        postgresql_where=sa.text("default_persona = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "_default_persona_name_idx",
        table_name="persona",
        postgresql_where=sa.text("default_persona = true"),
    )
    op.drop_column("persona", "datetime_aware")
