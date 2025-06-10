"""larger refresh tokens

Revision ID: cf90764725d8
Revises: 4794bc13e484
Create Date: 2025-04-04 10:56:39.769294

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "cf90764725d8"
down_revision = "4794bc13e484"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("oauth_account", "refresh_token", type_=sa.Text())


def downgrade() -> None:
    op.alter_column("oauth_account", "refresh_token", type_=sa.String(length=1024))
