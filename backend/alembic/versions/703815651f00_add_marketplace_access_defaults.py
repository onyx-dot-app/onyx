"""add marketplace access defaults

Revision ID: 703815651f00
Revises: 3833433b1585
Create Date: 2026-11-07 22:51:26.522151

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "703815651f00"
down_revision = "3833433b1585"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace", sa.Column("public_permission", sa.String(6), nullable=True)
    )
    op.add_column(
        "marketplace",
        sa.Column(
            "installation_policy",
            sa.String(13),
            nullable=False,
            server_default="AVAILABLE",
        ),
    )


def downgrade() -> None:
    op.drop_column("marketplace", "installation_policy")
    op.drop_column("marketplace", "public_permission")
