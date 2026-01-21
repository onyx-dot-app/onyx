"""add_processing_mode_to_connector_credential_pair

Revision ID: 0ab5805121ef
Revises: 7cd906f37fc6
Create Date: 2026-01-20 15:49:44.136116

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0ab5805121ef"
down_revision = "7cd906f37fc6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "processing_mode",
            sa.String(),
            nullable=False,
            server_default="REGULAR",
        ),
    )


def downgrade() -> None:
    op.drop_column("connector_credential_pair", "processing_mode")
