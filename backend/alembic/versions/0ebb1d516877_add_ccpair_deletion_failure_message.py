"""add ccpair deletion failure message

Revision ID: 0ebb1d516877
Revises: 52a219fb5233
Create Date: 2024-09-10 15:03:48.233926

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0ebb1d516877"
down_revision = "52a219fb5233"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column("deletion_failure_message", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connector_credential_pair", "deletion_failure_message")
