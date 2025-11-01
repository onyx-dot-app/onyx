"""add user type column to user table

Revision ID: 6ed95e5781c6
Revises: 09995b8811eb
Create Date: 2025-10-30 14:59:09.185957

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6ed95e5781c6"
down_revision = "09995b8811eb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the user_type column with a default value of 'HUMAN'
    op.add_column(
        "user",
        sa.Column("user_type", sa.String(), nullable=False, server_default="HUMAN"),
    )

    # Backfill existing service account users based on email pattern
    # Service account users have emails matching the pattern 'api_key__{name}@{uuid}onyxapikey.ai'
    op.execute(
        """
        UPDATE "user"
        SET user_type = 'SERVICE_ACCOUNT'
        WHERE email LIKE 'api\\_key\\_\\_%@%onyxapikey.ai' ESCAPE '\\'
    """
    )

    # Remove the server_default after data migration
    op.alter_column("user", "user_type", server_default=None)


def downgrade() -> None:
    # Remove the user_type column
    op.drop_column("user", "user_type")
