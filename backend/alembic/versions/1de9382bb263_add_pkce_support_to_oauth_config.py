"""Add PKCE support to OAuth config.

Revision ID: 1de9382bb263
Revises: 28bb08137807
Create Date: 2026-08-21 17:24:08.945170

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "1de9382bb263"
down_revision = "28bb08137807"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oauth_config",
        sa.Column(
            "supports_pkce",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("oauth_config", "supports_pkce")
