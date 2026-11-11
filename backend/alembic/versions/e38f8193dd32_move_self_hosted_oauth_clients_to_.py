"""move self hosted oauth clients to configured schema

The original OAuth client migration created the registry in public, even when
self-hosted installations configured a different application schema. Those
installations need public-schema privileges and store registrations outside
their application schema.

The corrected original migration uses the migration search_path for fresh
installations. Already-applied revisions do not run again, so this revision
moves existing registrations to POSTGRES_DEFAULT_SCHEMA. Moving the table
preserves client IDs, metadata, timestamps, and indexes.

Multi-tenant deployments retain their shared public catalog. Downgrade moves
the registry back to public for older application code and requires CREATE
permission on that schema.

Revision ID: e38f8193dd32
Revises: 4d8453213439
Create Date: 2026-10-21 10:11:43.106885

"""

from alembic import op
import sqlalchemy as sa

from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA

# revision identifiers, used by Alembic.
revision = "e38f8193dd32"
down_revision = "4d8453213439"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if MULTI_TENANT or POSTGRES_DEFAULT_SCHEMA == "public":
        return

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if not inspector.has_table("oauth_provider_client", schema="public"):
        return
    if inspector.has_table("oauth_provider_client", schema=POSTGRES_DEFAULT_SCHEMA):
        raise RuntimeError(
            "OAuth client registries exist in both public and the Onyx schema"
        )

    schema = connection.dialect.identifier_preparer.quote_schema(
        POSTGRES_DEFAULT_SCHEMA
    )
    op.execute(sa.text(f"ALTER TABLE public.oauth_provider_client SET SCHEMA {schema}"))


def downgrade() -> None:
    if MULTI_TENANT or POSTGRES_DEFAULT_SCHEMA == "public":
        return

    connection = op.get_bind()
    schema = connection.dialect.identifier_preparer.quote_schema(
        POSTGRES_DEFAULT_SCHEMA
    )
    op.execute(sa.text(f"ALTER TABLE {schema}.oauth_provider_client SET SCHEMA public"))
