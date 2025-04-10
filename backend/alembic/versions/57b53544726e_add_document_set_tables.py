"""Add document set tables

Revision ID: 57b53544726e
Revises: 800f48024ae9
Create Date: 2023-09-20 16:59:39.097177

"""

from alembic import op
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "57b53544726e"
down_revision = "800f48024ae9"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "document_set",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column("is_up_to_date", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "document_set__connector_credential_pair",
        sa.Column("document_set_id", sa.Integer(), nullable=False),
        sa.Column("connector_credential_pair_id", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connector_credential_pair_id"],
            ["connector_credential_pair.id"],
        ),
        sa.ForeignKeyConstraint(
            ["document_set_id"],
            ["document_set.id"],
        ),
        sa.PrimaryKeyConstraint(
            "document_set_id", "connector_credential_pair_id", "is_current"
        ),
    )


def downgrade() -> None:
    op.drop_table("document_set__connector_credential_pair")
    op.drop_table("document_set")
