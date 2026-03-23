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
from sqlalchemy.exc import IntegrityError


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


def _dedupe_null_notifications(connection: sa.Connection) -> None:
    # Multiple NULL-owned notifications can exist because the unique index treats
    # NULL user_id values as distinct. Before migrating them to the anonymous
    # user, collapse duplicates and remove rows that would conflict with an
    # already-existing anonymous notification.
    result = connection.execute(
        sa.text(
            """
            WITH ranked_null_notifications AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY notif_type, COALESCE(additional_data, '{}'::jsonb)
                        ORDER BY first_shown DESC, last_shown DESC, id DESC
                    ) AS row_num
                FROM notification
                WHERE user_id IS NULL
            )
            DELETE FROM notification
            WHERE id IN (
                SELECT id
                FROM ranked_null_notifications
                WHERE row_num > 1
            )
            """
        )
    )
    if result.rowcount > 0:
        print(f"Deleted {result.rowcount} duplicate NULL-owned notifications")

    result = connection.execute(
        sa.text(
            """
            DELETE FROM notification AS null_owned
            USING notification AS anonymous_owned
            WHERE null_owned.user_id IS NULL
              AND anonymous_owned.user_id = :user_id
              AND null_owned.notif_type = anonymous_owned.notif_type
              AND COALESCE(null_owned.additional_data, '{}'::jsonb) =
                  COALESCE(anonymous_owned.additional_data, '{}'::jsonb)
            """
        ),
        {"user_id": ANONYMOUS_USER_UUID},
    )
    if result.rowcount > 0:
        print(
            f"Deleted {result.rowcount} NULL-owned notifications that conflict with existing anonymous-owned notifications"
        )


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
            with connection.begin_nested():
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

                if table == "notification":
                    _dedupe_null_notifications(connection)

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
                    print(
                        f"Updated {result.rowcount} rows in {table} to anonymous user"
                    )
        except IntegrityError as e:
            if table == "notification":
                # IntegrityError is expected only for notification (unique constraint
                # on user_id + notif_type + additional_data). The dedup step above
                # should prevent this, but handle it gracefully just in case.
                print(f"Skipping {table} due to IntegrityError: {e}")
            else:
                print(f"Failed migrating {table} to anonymous user: {e}")
                raise


def downgrade() -> None:
    """
    Set anonymous user's records back to NULL and delete the anonymous user.

    Note: Duplicate NULL-owned notifications removed during upgrade are not restored.
    """
    connection = op.get_bind()

    # Set records back to NULL
    for table in TABLES_WITH_USER_ID:
        with connection.begin_nested():
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

    # Delete the anonymous user
    connection.execute(
        sa.text('DELETE FROM "user" WHERE id = :user_id'),
        {"user_id": ANONYMOUS_USER_UUID},
    )
