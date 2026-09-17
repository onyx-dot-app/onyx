"""add jwt auth columns to security settings

Revision ID: e7c00417d1e5
Revises: 28bb08137807
Create Date: 2026-08-21 12:27:35.945589

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e7c00417d1e5"
down_revision = "28bb08137807"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "security_settings",
        sa.Column("jwt_public_key_url", sa.String(), nullable=True),
    )
    op.add_column(
        "security_settings",
        sa.Column("jwt_expected_audience", sa.String(), nullable=True),
    )
    op.add_column(
        "security_settings",
        sa.Column("jwt_expected_issuer", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("security_settings", "jwt_expected_issuer")
    op.drop_column("security_settings", "jwt_expected_audience")
    op.drop_column("security_settings", "jwt_public_key_url")
