"""remove userfile related deprecated fields

Revision ID: a3c1a7904cd0
Revises: 5c3dca366b35
Create Date: 2026-01-06 13:00:30.634396

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a3c1a7904cd0"
down_revision = "5c3dca366b35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("user_file", "document_id")
    op.drop_column("user_file", "document_id_migrated")
    op.drop_column("connector_credential_pair", "is_user_file")


def downgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column("is_user_file", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "user_file",
        sa.Column("document_id", sa.String(), nullable=True),
    )
    op.add_column(
        "user_file",
        sa.Column(
            "document_id_migrated", sa.Boolean(), nullable=False, server_default="true"
        ),
    )
