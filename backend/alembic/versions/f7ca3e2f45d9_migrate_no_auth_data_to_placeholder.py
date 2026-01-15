"""migrate_no_auth_data_to_placeholder

This migration handles the transition from AUTH_TYPE=disabled to requiring
authentication. It creates a placeholder user and assigns all data that was
created without a user (user_id=NULL) to this placeholder.

When the first real user registers, their registration flow will transfer
all data from the placeholder user to the new user and delete the placeholder.

Revision ID: f7ca3e2f45d9
Revises: 73e9983e5091
Create Date: 2026-01-15 12:49:53.802741

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7ca3e2f45d9"
down_revision = "73e9983e5091"
branch_labels = None
depends_on = None

# Must match constants in onyx/configs/constants.py
NO_AUTH_PLACEHOLDER_USER_UUID = "00000000-0000-0000-0000-000000000001"
NO_AUTH_PLACEHOLDER_USER_EMAIL = "no-auth-placeholder@onyx.app"


def upgrade() -> None:
    """
    Create a placeholder user and assign all NULL user_id records to it.
    """
    connection = op.get_bind()

    # Check if there are any NULL user_id records that need migration
    tables_to_check = [
        "chat_session",
        "credential",
        "document_set",
        "persona",
        "tool",
        "notification",
        "inputprompt",
        "agent__search_metrics",
    ]

    has_null_records = False
    for table in tables_to_check:
        try:
            result = connection.execute(
                sa.text(f'SELECT 1 FROM "{table}" WHERE user_id IS NULL LIMIT 1')
            )
            if result.fetchone():
                has_null_records = True
                break
        except Exception:
            # Table might not exist
            pass

    if not has_null_records:
        print("No NULL user_id records found. Skipping placeholder user creation.")
        return

    # Check if placeholder user already exists
    result = connection.execute(
        sa.text('SELECT id FROM "user" WHERE id = :user_id'),
        {"user_id": NO_AUTH_PLACEHOLDER_USER_UUID},
    )
    if result.fetchone():
        print("Placeholder user already exists. Skipping creation.")
    else:
        # Create the placeholder user
        # Using raw SQL to avoid ORM dependencies
        connection.execute(
            sa.text(
                """
                INSERT INTO "user" (id, email, hashed_password, is_active, is_superuser, is_verified, role)
                VALUES (:id, :email, :hashed_password, :is_active, :is_superuser, :is_verified, :role)
                """
            ),
            {
                "id": NO_AUTH_PLACEHOLDER_USER_UUID,
                "email": NO_AUTH_PLACEHOLDER_USER_EMAIL,
                "hashed_password": "",  # Empty password - user cannot log in
                "is_active": False,  # Inactive - user cannot log in
                "is_superuser": False,
                "is_verified": False,
                "role": "BASIC",
            },
        )
        print(f"Created placeholder user: {NO_AUTH_PLACEHOLDER_USER_EMAIL}")

    # Assign NULL user_id records to the placeholder user
    for table in tables_to_check:
        try:
            # Exclude public credential (id=0) which must remain user_id=NULL
            # Exclude builtin tools (in_code_tool_id IS NOT NULL) which must remain user_id=NULL
            if table == "credential":
                condition = "user_id IS NULL AND id != 0"
            elif table == "tool":
                condition = "user_id IS NULL AND in_code_tool_id IS NULL"
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
                {"user_id": NO_AUTH_PLACEHOLDER_USER_UUID},
            )
            if result.rowcount > 0:
                print(f"Updated {result.rowcount} rows in {table}")
        except Exception as e:
            print(f"Skipping {table}: {e}")


def downgrade() -> None:
    """
    Set placeholder user's records back to NULL and delete the placeholder user.
    """
    connection = op.get_bind()

    tables_to_update = [
        "chat_session",
        "credential",
        "document_set",
        "persona",
        "tool",
        "notification",
        "inputprompt",
        "agent__search_metrics",
    ]

    # Set records back to NULL
    for table in tables_to_update:
        try:
            connection.execute(
                sa.text(
                    f"""
                    UPDATE "{table}"
                    SET user_id = NULL
                    WHERE user_id = :user_id
                    """
                ),
                {"user_id": NO_AUTH_PLACEHOLDER_USER_UUID},
            )
        except Exception:
            pass

    # Delete the placeholder user
    connection.execute(
        sa.text('DELETE FROM "user" WHERE id = :user_id'),
        {"user_id": NO_AUTH_PLACEHOLDER_USER_UUID},
    )
