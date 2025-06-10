"""Private Personas DocumentSets

Revision ID: e91df4e935ef
Revises: 91fd3b470d1a
Create Date: 2024-03-17 11:47:24.675881

"""

import fastapi_users_db_sqlalchemy
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e91df4e935ef"
down_revision = "91fd3b470d1a"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "document_set__user",
        sa.Column("document_set_id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_set_id"],
            ["document_set.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("document_set_id", "user_id"),
    )
    op.create_table(
        "persona__user",
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("persona_id", "user_id"),
    )
    op.create_table(
        "document_set__user_group",
        sa.Column("document_set_id", sa.Integer(), nullable=False),
        sa.Column(
            "user_group_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_set_id"],
            ["document_set.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_group_id"],
            ["user_group.id"],
        ),
        sa.PrimaryKeyConstraint("document_set_id", "user_group_id"),
    )
    op.create_table(
        "persona__user_group",
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column(
            "user_group_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_group_id"],
            ["user_group.id"],
        ),
        sa.PrimaryKeyConstraint("persona_id", "user_group_id"),
    )

    op.add_column(
        "document_set",
        sa.Column("is_public", sa.Boolean(), nullable=True),
    )
    # fill in is_public for existing rows
    op.execute("UPDATE document_set SET is_public = true WHERE is_public IS NULL")
    op.alter_column("document_set", "is_public", nullable=False)

    op.add_column(
        "persona",
        sa.Column("is_public", sa.Boolean(), nullable=True),
    )
    # fill in is_public for existing rows
    op.execute("UPDATE persona SET is_public = true WHERE is_public IS NULL")
    op.alter_column("persona", "is_public", nullable=False)


def downgrade() -> None:
    op.drop_column("persona", "is_public")

    op.drop_column("document_set", "is_public")

    op.drop_table("persona__user")
    op.drop_table("document_set__user")
    op.drop_table("persona__user_group")
    op.drop_table("document_set__user_group")
