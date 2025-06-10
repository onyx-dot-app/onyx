"""extended_role_for_non_web

Revision ID: dfbe9e93d3c7
Revises: 9cf5c00f72fe
Create Date: 2024-11-16 07:54:18.727906

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "dfbe9e93d3c7"
down_revision = "9cf5c00f72fe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE "user"
        SET role = 'EXT_PERM_USER'
        WHERE has_web_login = false
    """
    )
    op.drop_column("user", "has_web_login")


def downgrade() -> None:
    op.add_column(
        "user",
        sa.Column("has_web_login", sa.Boolean(), nullable=False, server_default="true"),
    )

    op.execute(
        """
        UPDATE "user"
        SET has_web_login = false,
            role = 'BASIC'
        WHERE role IN ('SLACK_USER', 'EXT_PERM_USER')
    """
    )
