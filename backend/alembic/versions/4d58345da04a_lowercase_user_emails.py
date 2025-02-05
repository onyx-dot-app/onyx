"""lowercase_user_emails

Revision ID: 4d58345da04a
Revises: f1ca58b2f2ec
Create Date: 2025-01-29 07:48:46.784041

"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = "4d58345da04a"
down_revision = "f1ca58b2f2ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get database connection
    connection = op.get_bind()

    # Update all user emails to lowercase
    connection.execute(
        text(
            """
            UPDATE "user"
            SET email = LOWER(email)
            WHERE email != LOWER(email)
            """
        )
    )


def downgrade() -> None:
    # Cannot restore original case of emails
    pass
