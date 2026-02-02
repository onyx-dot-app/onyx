"""create_anonymous_user

This migration creates a permanent anonymous user in the database.
When anonymous access is enabled, unauthenticated requests will use this user
instead of returning user_id=NULL.

Revision ID: e7f8a9b0c1d2
Revises: f7ca3e2f45d9
Create Date: 2026-01-15 14:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e7f8a9b0c1d2"
down_revision = "f7ca3e2f45d9"
branch_labels = None
depends_on = None

# Must match constants in onyx/configs/constants.py file
ANONYMOUS_USER_UUID = "00000000-0000-0000-0000-000000000002"
ANONYMOUS_USER_EMAIL = "anonymous@onyx.app"

# Tables with user_id foreign key that may need migration
TABLES_WITH_USER_ID = [
    "chat_session",
    "credential",
    "document_set",
    "persona",
    "tool",
    "notification",
    "inputprompt",
]


def upgrade() -> None:
    """
    Create the anonymous user for anonymous access feature.
    Also migrates any remaining user_id=NULL records to the anonymous user.
    """
    connection = op.get_bind()

    # Create the anonymous user (using ON CONFLICT to be idempotent)
    connection.execute(
        sa.text(
            """
            INSERT INTO "user" (id, email, hashed_password, is_active, is_superuser, is_verified, role)
            VALUES (:id, :email, :hashed_password, :is_active, :is_superuser, :is_verified, :role)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": ANONYMOUS_USER_UUID,
            "email": ANONYMOUS_USER_EMAIL,
            "hashed_password": "",  # Empty password - user cannot log in directly
            "is_active": True,  # Active so it can be used for anonymous access
            "is_superuser": False,
            "is_verified": True,  # Verified since no email verification needed
            "role": "LIMITED",  # Anonymous users have limited role to restrict access
        },
    )

    # Migrate any remaining user_id=NULL records to anonymous user
    for table in TABLES_WITH_USER_ID:
        try:
            # Exclude public credential (id=0) which must remain user_id=NULL
            # Exclude builtin tools (in_code_tool_id IS NOT NULL) which must remain user_id=NULL
            # Exclude builtin personas (builtin_persona=True) which must remain user_id=NULL
            # Exclude system input prompts (is_public=True with user_id=NULL) which must remain user_id=NULL
            if table == "credential":
                condition = "user_id IS NULL AND id != 0"
            elif table == "tool":
                condition = "user_id IS NULL AND in_code_tool_id IS NULL"
            elif table == "persona":
                condition = "user_id IS NULL AND builtin_persona = false"
            elif table == "inputprompt":
                condition = "user_id IS NULL AND is_public = false"
            else:
                condition = "user_id IS NULL"
            result = connection.execute(
                sa.text(
                    f"""
                    UPDATE "{table}"
                    SET user_id = :user_id
                    WHERE {condition}
                    """
                ),
                {"user_id": ANONYMOUS_USER_UUID},
            )
            if result.rowcount > 0:
                print(f"Updated {result.rowcount} rows in {table} to anonymous user")
        except Exception as e:
            print(f"Skipping {table}: {e}")


def downgrade() -> None:
    """
    Set anonymous user's records back to NULL and delete the anonymous user.
    """
    connection = op.get_bind()

    # Set records back to NULL
    for table in TABLES_WITH_USER_ID:
        try:
            connection.execute(
                sa.text(
                    f"""
                    UPDATE "{table}"
                    SET user_id = NULL
                    WHERE user_id = :user_id
                    """
                ),
                {"user_id": ANONYMOUS_USER_UUID},
            )
        except Exception:
            pass

    # Delete the anonymous user
    connection.execute(
        sa.text('DELETE FROM "user" WHERE id = :user_id'),
        {"user_id": ANONYMOUS_USER_UUID},
    )
