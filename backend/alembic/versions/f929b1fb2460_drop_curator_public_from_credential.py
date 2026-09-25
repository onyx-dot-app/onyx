"""drop curator_public from credential

Revision ID: f929b1fb2460
Revises: df879de08494
Create Date: 2026-09-24 09:19:34.568511

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f929b1fb2460"
down_revision = "df879de08494"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("credential", "curator_public")


def downgrade() -> None:
    op.add_column(
        "credential",
        sa.Column(
            "curator_public",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
