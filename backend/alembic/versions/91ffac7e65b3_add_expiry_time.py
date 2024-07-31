"""add expiry time

Revision ID: 91ffac7e65b3
Revises: bc9771dccadf
Create Date: 2024-06-24 09:39:56.462242

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "91ffac7e65b3"
down_revision = "795b20b85b4b"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "user", sa.Column("oidc_expiry", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user", "oidc_expiry")
