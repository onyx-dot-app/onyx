"""lowercase_user_emails

Revision ID: 4d58345da04a
Revises: f1ca58b2f2ec
Create Date: 2025-01-29 07:48:46.784041

"""

import logging
from typing import cast
from alembic import op
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = "4d58345da04a"
down_revision = "f1ca58b2f2ec"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """Conflicts on lowercasing will result in the uppercased email getting a
    unique integer suffix when converted to lowercase."""

    connection = op.get_bind()

    # Fetch all user emails that are not already lowercase
    user_emails = connection.execute(
        text('SELECT id, email FROM "user" WHERE email != LOWER(email)')
    ).fetchall()

    for user_id, email in user_emails:
        email = cast(str, email)
        username, domain = email.rsplit("@", 1)
        new_email = f"{username.lower()}@{domain.lower()}"
        attempt = 1

        while True:
            try:
                # Try updating the email
                connection.execute(
                    text('UPDATE "user" SET email = :new_email WHERE id = :user_id'),
                    {"new_email": new_email, "user_id": user_id},
                )
                break  # Success, exit loop
            except IntegrityError:
                next_email = f"{username.lower()}_{attempt}@{domain.lower()}"
                # Email conflict occurred, append `_1`, `_2`, etc., to the username
                logger.warning(
                    f"Conflict while lowercasing email: "
                    f"old_email={email} "
                    f"conflicting_email={new_email} "
                    f"next_email={next_email}"
                )
                new_email = next_email
                attempt += 1


def downgrade() -> None:
    # Cannot restore original case of emails
    pass
