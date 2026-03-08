"""add_db_readonly_user

Revision ID: 3b9f09038764
Revises: 3b45e0018bf1
Create Date: 2025-05-11 11:05:11.436977

"""

from sqlalchemy import text

from alembic import op
from onyx.configs.app_configs import DB_READONLY_PASSWORD
from onyx.configs.app_configs import DB_READONLY_USER


# revision identifiers, used by Alembic.
revision = "3b9f09038764"
down_revision = "3b45e0018bf1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pg_trgm extension if not already enabled
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Create the read-only db user if it does not already exist.
    if not (DB_READONLY_USER and DB_READONLY_PASSWORD):
        raise Exception("DB_READONLY_USER or DB_READONLY_PASSWORD is not set")

    op.execute(
        text(
            f"""
            DO $$
            BEGIN
                -- Check if the read-only user already exists
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{DB_READONLY_USER}') THEN
                    -- Create the read-only user with the specified password
                    EXECUTE format('CREATE USER %I WITH PASSWORD %L', '{DB_READONLY_USER}', '{DB_READONLY_PASSWORD}');
                    -- First revoke all privileges to ensure a clean slate
                    EXECUTE format('REVOKE ALL ON DATABASE %I FROM %I', current_database(), '{DB_READONLY_USER}');
                    -- Grant only the CONNECT privilege to allow the user to connect to the database
                    -- but not perform any operations without additional specific grants
                    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), '{DB_READONLY_USER}');
                END IF;
            END
            $$;
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{DB_READONLY_USER}') THEN
                -- First revoke all privileges from the database
                EXECUTE format('REVOKE ALL ON DATABASE %I FROM %I', current_database(), '{DB_READONLY_USER}');
                -- Then revoke all privileges from the public schema
                EXECUTE format('REVOKE ALL ON SCHEMA public FROM %I', '{DB_READONLY_USER}');
                -- Then drop the user
                EXECUTE format('DROP USER %I', '{DB_READONLY_USER}');
            END IF;
        END
        $$;
    """
        )
    )
    op.execute(text("DROP EXTENSION IF EXISTS pg_trgm"))
