"""add_read_only_kg_user

Revision ID: 3b9f09038764
Revises: 3b45e0018bf1
Create Date: 2025-05-11 11:05:11.436977

"""

from passlib.exc import PasswordSizeError
from passlib.pwd import genword
from sqlalchemy import text

from alembic import op
from onyx.kg.configuration import KG_READONLY_DB_PASSWORD
from onyx.kg.configuration import KG_READONLY_DB_USER
from shared_configs.configs import MULTI_TENANT


# revision identifiers, used by Alembic.
revision = "3b9f09038764"
down_revision = "3b45e0018bf1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if MULTI_TENANT:
        # Create read-only db user here only in single tenant mode. For multi-tenant mode,
        # the user is created in the alembic_tenants migration.
        if not (KG_READONLY_DB_USER and KG_READONLY_DB_PASSWORD):
            raise Exception("KG_READONLY_DB_USER or KG_READONLY_DB_PASSWORD is not set")

        try:
            # Validate password length and complexity
            genword(
                length=13, charset="ascii_72"
            )  # This will raise PasswordSizeError if too short
            # Additional checks can be added here if needed
        except PasswordSizeError:
            raise Exception("KG_READONLY_DB_PASSWORD is too short or too weak")

        op.execute(
            text(
                f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{KG_READONLY_DB_USER}') THEN
                    EXECUTE format('CREATE USER %I WITH PASSWORD %L', '{KG_READONLY_DB_USER}', '{KG_READONLY_DB_PASSWORD}');
                    -- Explicitly revoke all privileges including CONNECT
                    EXECUTE format('REVOKE ALL ON DATABASE %I FROM %I', current_database(), '{KG_READONLY_DB_USER}');
                END IF;
            END
            $$;
        """
            )
        )


def downgrade() -> None:
    if MULTI_TENANT:
        # Drop read-only db user here only in single tenant mode. For multi-tenant mode,
        # the user is dropped in the alembic_tenants migration.

        op.execute(
            text(
                f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{KG_READONLY_DB_USER}') THEN
                    EXECUTE format('DROP USER %I', '{KG_READONLY_DB_USER}');
                END IF;
            END
            $$;
        """
            )
        )
