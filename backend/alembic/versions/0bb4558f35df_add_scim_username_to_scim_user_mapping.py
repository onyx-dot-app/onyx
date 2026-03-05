"""add scim_username to scim_user_mapping

Revision ID: 0bb4558f35df
Revises: 631fd2504136
Create Date: 2026-02-20 10:45:30.340188

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0bb4558f35df"
down_revision = "631fd2504136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scim_user_mapping",
        sa.Column("scim_username", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scim_user_mapping", "scim_username")
