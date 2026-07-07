"""add sso_provider table and seed from env

Revision ID: 1fc2904131a3
Revises: 2e0b2b146de1
Create Date: 2026-07-06 21:34:08.516250

"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

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
        # Protocol-specific config, encrypted JSON (matches the EncryptedJson
        # ORM column). Shape differs by provider_type; validated in the app.
        sa.Column("config", sa.LargeBinary, nullable=False),
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
    """One-time import of legacy single-provider config. The DB is the source
    of truth afterwards; env vars are never read at request time.

    Reads the already-resolved app_config constants (not raw os.environ) so
    the legacy GOOGLE_OAUTH_* fallbacks and the VALID_EMAIL_DOMAINS parsing
    stay in one place. Skipped in multi-tenant (cloud auth does not use
    per-instance provider rows) and when the table already has any row.
    """
    from onyx.configs.app_configs import AUTH_TYPE
    from onyx.configs.app_configs import OAUTH_CLIENT_ID
    from onyx.configs.app_configs import OAUTH_CLIENT_SECRET
    from onyx.configs.app_configs import OPENID_CONFIG_URL
    from onyx.configs.app_configs import VALID_EMAIL_DOMAINS
    from onyx.configs.constants import AuthType
    from shared_configs.configs import MULTI_TENANT

    if MULTI_TENANT:
        return

    # provider_type is the enum member NAME (Enum(native_enum=False) storage);
    # the login `name` matches the oauth_name existing linked accounts carry so
    # linkage survives the routing cutover.
    if AUTH_TYPE == AuthType.GOOGLE_OAUTH:
        provider_type, name = "GOOGLE", "google"
        display_name, config_url = "Continue with Google", None
    elif AUTH_TYPE == AuthType.OIDC:
        if not OPENID_CONFIG_URL:
            return
        provider_type, name = "OIDC", "openid"
        display_name, config_url = "Single Sign-On", OPENID_CONFIG_URL
    else:
        return

    if not OAUTH_CLIENT_ID or not OAUTH_CLIENT_SECRET:
        return

    bind = op.get_bind()
    if bind.execute(sa.select(table.c.id).limit(1)).first():
        return

    # Config shape matches the per-type models in onyx.db.sso_provider, encrypted
    # exactly as the EncryptedJson column would store it (json then encrypt).
    config: dict[str, str] = {
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": OAUTH_CLIENT_SECRET,
    }
    if config_url is not None:
        config["openid_config_url"] = config_url

    bind.execute(
        table.insert().values(
            name=name,
            display_name=display_name,
            provider_type=provider_type,
            config=encrypt_string_to_bytes(json.dumps(config)),
            allowed_email_domains=[d.lower() for d in VALID_EMAIL_DOMAINS],
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
