"""restrict no auth data transfer to standard users

The f7ca3e2f45d9 trigger gave the no-auth data to the first inserted user row.
Bot, external-permission, and service-account rows are inserted without a
registration, so they could take the data. This revision replaces the trigger
function, if it is still installed, so that only an active STANDARD user
with a real email takes the data. A second trigger also fires when a
registrant upgrades such a row to STANDARD.

Revision ID: c9d4c7acacdd
Revises: a27d64f7b810
Create Date: 2026-10-13 16:07:57.277221

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9d4c7acacdd"
down_revision = "a27d64f7b810"
branch_labels = None
depends_on = None

TRIGGER_NAME = "trg_migrate_no_auth_data"
UPGRADE_TRIGGER_NAME = "trg_migrate_no_auth_data_on_upgrade"
FUNCTION_NAME = "migrate_no_auth_data_to_user"

# Must match DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN in onyx/configs/constants.py.
# Key emails end with "@<uuid>onyxapikey.ai", so match the suffix only.
API_KEY_EMAIL_DOMAIN = "onyxapikey.ai"

_GUARD_PLACEHOLDER = "-- __ACCOUNT_GUARD__"

ORIGINAL_GUARD = """
    IF NEW.is_active = FALSE THEN
        RETURN NULL;
    END IF;
"""

STANDARD_ONLY_GUARD = f"""
    IF NEW.is_active IS NOT TRUE
        OR NEW.account_type IS DISTINCT FROM 'STANDARD'
        OR lower(NEW.email) LIKE '%{API_KEY_EMAIL_DOMAIN}'
    THEN
        RETURN NULL;
    END IF;
"""

# Same body as f7ca3e2f45d9; only the account guard differs.
TRIGGER_FUNCTION_TEMPLATE = f"""
CREATE OR REPLACE FUNCTION {FUNCTION_NAME}()
RETURNS TRIGGER AS $$
DECLARE
    placeholder_uuid UUID := '00000000-0000-0000-0000-000000000001'::uuid;
    anonymous_uuid UUID := '00000000-0000-0000-0000-000000000002'::uuid;
    placeholder_row RECORD;
    schema_name TEXT;
BEGIN
    IF NEW.id = placeholder_uuid THEN
        RETURN NULL;
    END IF;

    IF NEW.id = anonymous_uuid THEN
        RETURN NULL;
    END IF;
{_GUARD_PLACEHOLDER}
    schema_name := current_schema();

    SELECT id INTO placeholder_row
    FROM "user"
    WHERE id = placeholder_uuid
    FOR UPDATE SKIP LOCKED;

    IF NOT FOUND THEN
        EXECUTE format('DROP TRIGGER IF EXISTS {TRIGGER_NAME} ON %I."user"', schema_name);
        EXECUTE format('DROP TRIGGER IF EXISTS {UPGRADE_TRIGGER_NAME} ON %I."user"', schema_name);
        EXECUTE format('DROP FUNCTION IF EXISTS %I.{FUNCTION_NAME}()', schema_name);
        RETURN NULL;
    END IF;

    UPDATE "chat_session" SET user_id = NEW.id WHERE user_id = placeholder_uuid;
    UPDATE "credential" SET user_id = NEW.id WHERE user_id = placeholder_uuid AND id != 0;
    UPDATE "document_set" SET user_id = NEW.id WHERE user_id = placeholder_uuid;
    UPDATE "persona" SET user_id = NEW.id WHERE user_id = placeholder_uuid AND builtin_persona = FALSE;
    UPDATE "tool" SET user_id = NEW.id WHERE user_id = placeholder_uuid AND in_code_tool_id IS NULL;
    UPDATE "notification" SET user_id = NEW.id WHERE user_id = placeholder_uuid;
    UPDATE "inputprompt" SET user_id = NEW.id WHERE user_id = placeholder_uuid AND is_public = FALSE;

    UPDATE "user" SET role = 'ADMIN' WHERE id = NEW.id;

    DELETE FROM "user" WHERE id = placeholder_uuid;

    EXECUTE format('DROP TRIGGER IF EXISTS {TRIGGER_NAME} ON %I."user"', schema_name);
    EXECUTE format('DROP TRIGGER IF EXISTS {UPGRADE_TRIGGER_NAME} ON %I."user"', schema_name);
    EXECUTE format('DROP FUNCTION IF EXISTS %I.{FUNCTION_NAME}()', schema_name);

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

# BOT and EXT_PERM_USER rows become STANDARD by UPDATE when their owner registers.
UPGRADE_TRIGGER = f"""
CREATE TRIGGER {UPGRADE_TRIGGER_NAME}
AFTER UPDATE OF account_type ON "user"
FOR EACH ROW
WHEN (
    OLD.account_type IS DISTINCT FROM 'STANDARD'
    AND NEW.account_type = 'STANDARD'
)
EXECUTE FUNCTION {FUNCTION_NAME}();
"""


def _function_installed() -> bool:
    result = op.get_bind().execute(
        sa.text("""
            SELECT 1 FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE p.proname = :name AND n.nspname = current_schema()
            """),
        {"name": FUNCTION_NAME},
    )
    return result.first() is not None


def _replace_function(guard: str) -> bool:
    # The trigger drops itself after the first transfer. Do not reinstall it.
    if not _function_installed():
        return False
    op.execute(sa.text(TRIGGER_FUNCTION_TEMPLATE.replace(_GUARD_PLACEHOLDER, guard)))
    return True


def upgrade() -> None:
    if _replace_function(STANDARD_ONLY_GUARD):
        op.execute(sa.text(f'DROP TRIGGER IF EXISTS {UPGRADE_TRIGGER_NAME} ON "user"'))
        op.execute(sa.text(UPGRADE_TRIGGER))


def downgrade() -> None:
    op.execute(sa.text(f'DROP TRIGGER IF EXISTS {UPGRADE_TRIGGER_NAME} ON "user"'))
    _replace_function(ORIGINAL_GUARD)
