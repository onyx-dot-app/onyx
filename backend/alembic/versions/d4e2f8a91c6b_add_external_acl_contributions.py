"""add external ACL contributions

Revision ID: d4e2f8a91c6b
Revises: ac05f4a21dbd
Create Date: 2026-09-25 22:40:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "d4e2f8a91c6b"
down_revision = "ac05f4a21dbd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_by_connector_credential_pair",
        sa.Column("external_user_emails", sa.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "document_by_connector_credential_pair",
        sa.Column("external_user_group_ids", sa.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "document_by_connector_credential_pair",
        sa.Column("is_public", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_by_connector_credential_pair", "is_public")
    op.drop_column("document_by_connector_credential_pair", "external_user_group_ids")
    op.drop_column("document_by_connector_credential_pair", "external_user_emails")
