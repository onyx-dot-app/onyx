"""add sso_provider table and seed from env

Revision ID: 1fc2904131a3
Revises: 2e0b2b146de1
Create Date: 2026-07-06 21:34:08.516250

"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from dotenv import load_dotenv, find_dotenv

from onyx.utils.encryption import encrypt_string_to_bytes

# revision identifiers, used by Alembic.
revision = "1fc2904131a3"
down_revision = "2e0b2b146de1"
branch_labels = None
depends_on = None


def _sso_provider_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "sso_provider",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("display_name", sa.String, nullable=False),
        sa.Column("provider_type", sa.String, nullable=False),
        sa.Column("client_id", sa.String, nullable=False),
        sa.Column("client_secret", sa.LargeBinary, nullable=False),
        sa.Column("openid_config_url", sa.String, nullable=True),
        sa.Column(
            "allowed_email_domains",
            postgresql.ARRAY(sa.String),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def _seed_from_env(table: sa.Table) -> None:
    """One-time import of legacy single-provider env config. The DB is the
    source of truth afterwards; env vars are never read at request time.

    Skipped in multi-tenant (cloud auth does not use per-instance provider
    rows) and when the table already has any row.
    """
    load_dotenv(find_dotenv())

    if os.environ.get("MULTI_TENANT", "").lower() == "true":
        return

    auth_type = os.environ.get("AUTH_TYPE", "").lower()
    client_id = os.environ.get("OAUTH_CLIENT_ID")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET")
    openid_config_url = os.environ.get("OPENID_CONFIG_URL")

    # Seed names match the oauth_name that existing linked login accounts
    # carry ("google" / "openid"), so account linkage survives the cutover
    # to provider-row routing.
    if auth_type == "google_oauth":
        provider_type, name, display_name = "google", "google", "Continue with Google"
        config_url = None
    elif auth_type == "oidc":
        if not openid_config_url:
            return
        provider_type, name, display_name = "oidc", "openid", "Single Sign-On"
        config_url = openid_config_url
    else:
        return

    if not client_id or not client_secret:
        return

    bind = op.get_bind()
    if bind.execute(sa.select(table.c.id).limit(1)).first():
        return

    allowed_email_domains = [
        domain.strip().lower()
        for domain in os.environ.get("VALID_EMAIL_DOMAINS", "").split(",")
        if domain.strip()
    ]

    bind.execute(
        table.insert().values(
            name=name,
            display_name=display_name,
            provider_type=provider_type,
            client_id=client_id,
            client_secret=encrypt_string_to_bytes(client_secret),
            openid_config_url=config_url,
            allowed_email_domains=allowed_email_domains,
            enabled=True,
        )
    )


def upgrade() -> None:
    metadata = sa.MetaData()
    table = _sso_provider_table(metadata)
    table.create(op.get_bind())
    _seed_from_env(table)


def downgrade() -> None:
    op.drop_table("sso_provider")
