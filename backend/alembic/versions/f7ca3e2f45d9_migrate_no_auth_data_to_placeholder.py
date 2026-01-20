"""migrate_no_auth_data_to_placeholder

This migration handles the transition from AUTH_TYPE=disabled to requiring
authentication. It creates a placeholder user and assigns all data that was
created without a user (user_id=NULL) to this placeholder.

A database trigger is installed that automatically transfers all data from
the placeholder user to the first real user who registers, then drops itself.

Revision ID: f7ca3e2f45d9
Revises: 8b5ce697290e
Create Date: 2026-01-15 12:49:53.802741

"""

from alembic import op
import sqlalchemy as sa

from shared_configs.configs import MULTI_TENANT


# revision identifiers, used by Alembic.
revision = "f7ca3e2f45d9"
down_revision = "8b5ce697290e"
branch_labels = None
depends_on = None

# Must match constants in onyx/configs/constants.py file
NO_AUTH_PLACEHOLDER_USER_UUID = "00000000-0000-0000-0000-000000000001"
NO_AUTH_PLACEHOLDER_USER_EMAIL = "no-auth-placeholder@onyx.app"


# Trigger function that migrates data from placeholder to first real user
MIGRATE_NO_AUTH_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION migrate_no_auth_data_to_user()
RETURNS TRIGGER AS $$
DECLARE
    placeholder_uuid UUID := '00000000-0000-0000-0000-000000000001'::uuid;
    anonymous_uuid UUID := '00000000-0000-0000-0000-000000000002'::uuid;
    placeholder_row RECORD;
    schema_name TEXT;
BEGIN
    -- Skip if this is the placeholder user being inserted
    IF NEW.id = placeholder_uuid THEN
        RETURN NULL;
    END IF;

    -- Skip if this is the anonymous user being inserted (not a real user)
    IF NEW.id = anonymous_uuid THEN
        RETURN NULL;
    END IF;

    -- Skip if the new user is not active
    IF NEW.is_active = FALSE THEN
        RETURN NULL;
    END IF;

    -- Get current schema for self-cleanup
    schema_name := current_schema();

    -- Try to lock the placeholder user row with FOR UPDATE SKIP LOCKED
    -- This ensures only one concurrent transaction can proceed with migration
    -- SKIP LOCKED means if another transaction has the lock, we skip (don't wait)
    SELECT id INTO placeholder_row
    FROM "user"
    WHERE id = placeholder_uuid
    FOR UPDATE SKIP LOCKED;

    IF NOT FOUND THEN
        -- Either placeholder doesn't exist or another transaction has it locked
        -- Either way, drop the trigger and return without making admin
        EXECUTE format('DROP TRIGGER IF EXISTS trg_migrate_no_auth_data ON %I."user"', schema_name);
        EXECUTE format('DROP FUNCTION IF EXISTS %I.migrate_no_auth_data_to_user()', schema_name);
        RETURN NULL;
    END IF;

    -- We have exclusive lock on placeholder - proceed with migration
    -- The INSERT has already completed (AFTER INSERT), so NEW.id exists in the table

    -- Migrate chat_session
    UPDATE "chat_session" SET user_id = NEW.id WHERE user_id = placeholder_uuid;

    -- Migrate credential (exclude public credential id=0)
    UPDATE "credential" SET user_id = NEW.id WHERE user_id = placeholder_uuid AND id != 0;

    -- Migrate document_set
    UPDATE "document_set" SET user_id = NEW.id WHERE user_id = placeholder_uuid;

    -- Migrate persona
    UPDATE "persona" SET user_id = NEW.id WHERE user_id = placeholder_uuid;

    -- Migrate tool (exclude builtin tools)
    UPDATE "tool" SET user_id = NEW.id WHERE user_id = placeholder_uuid AND in_code_tool_id IS NULL;

    -- Migrate notification
    UPDATE "notification" SET user_id = NEW.id WHERE user_id = placeholder_uuid;

    -- Migrate inputprompt
    UPDATE "inputprompt" SET user_id = NEW.id WHERE user_id = placeholder_uuid;

    -- Make the new user an admin (they had admin access in no-auth mode)
    -- In AFTER INSERT trigger, we must UPDATE the row since it already exists
    UPDATE "user" SET role = 'ADMIN' WHERE id = NEW.id;

    -- Delete the placeholder user (we hold the lock so this is safe)
    DELETE FROM "user" WHERE id = placeholder_uuid;

    -- Drop the trigger and function (self-cleanup)
    EXECUTE format('DROP TRIGGER IF EXISTS trg_migrate_no_auth_data ON %I."user"', schema_name);
    EXECUTE format('DROP FUNCTION IF EXISTS %I.migrate_no_auth_data_to_user()', schema_name);

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

MIGRATE_NO_AUTH_TRIGGER = """
CREATE TRIGGER trg_migrate_no_auth_data
AFTER INSERT ON "user"
FOR EACH ROW
EXECUTE FUNCTION migrate_no_auth_data_to_user();
"""


def upgrade() -> None:
    """
    Create a placeholder user and assign all NULL user_id records to it.
    Install a trigger that migrates data to the first real user and self-destructs.
    Only runs if no real users exist (true AUTH_TYPE=disabled deployment).

    Skipped in multi-tenant mode - each tenant starts fresh with no legacy data.
    """
    # Skip in multi-tenant mode - this migration handles single-tenant
    # AUTH_TYPE=disabled -> auth transitions only
    if MULTI_TENANT:
        return

    connection = op.get_bind()

    # Check if any real users exist in the database
    # If users exist, this deployment was NOT using AUTH_TYPE=disabled
    # and user_id=NULL data is likely from anonymous users - don't migrate
    result = connection.execute(sa.text('SELECT 1 FROM "user" LIMIT 1'))
    if result.fetchone():
        print("Existing users found. This deployment was not using AUTH_TYPE=disabled.")
        print("Skipping migration - user_id=NULL data is likely from anonymous users.")
        return

    # Check if there are any NULL user_id records that need migration
    tables_to_check = [
        "chat_session",
        "credential",
        "document_set",
        "persona",
        "tool",
        "notification",
        "inputprompt",
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

    # Assign NULL user_id records to the placeholder user
    for table in tables_to_check:
        try:
            # Base condition for all tables
            condition = "user_id IS NULL"
            # Exclude public credential (id=0) which must remain user_id=NULL
            if table == "credential":
                condition += " AND id != 0"
            # Exclude builtin tools (in_code_tool_id IS NOT NULL) which must remain user_id=NULL
            elif table == "tool":
                condition += " AND in_code_tool_id IS NULL"
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

    # Install the trigger function and trigger for automatic migration on first user registration
    connection.execute(sa.text(MIGRATE_NO_AUTH_TRIGGER_FUNCTION))
    connection.execute(sa.text(MIGRATE_NO_AUTH_TRIGGER))
    print("Installed trigger for automatic data migration on first user registration")


def downgrade() -> None:
    """
    Drop trigger and function, set placeholder user's records back to NULL,
    and delete the placeholder user.
    """
    connection = op.get_bind()

    # Drop trigger and function if they exist (they may have already self-destructed)
    connection.execute(
        sa.text('DROP TRIGGER IF EXISTS trg_migrate_no_auth_data ON "user"')
    )
    connection.execute(
        sa.text("DROP FUNCTION IF EXISTS migrate_no_auth_data_to_user()")
    )

    tables_to_update = [
        "chat_session",
        "credential",
        "document_set",
        "persona",
        "tool",
        "notification",
        "inputprompt",
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
