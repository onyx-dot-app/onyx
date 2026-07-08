"""import SAML_CONF_DIR settings into sso_provider

Revision ID: c8d1a4b7e920
Revises: 1fc2904131a3
Create Date: 2026-07-07 18:10:00.000000

Seeds a SAML provider row from a legacy single-config SAML_CONF_DIR so the
deployment can manage and extend it as a row. The legacy /auth/saml/* route
stays mounted and keeps serving the existing login, so this does not cut anyone
over. Moving to the parametric /auth/saml/<name>/* route requires updating the
IdP's ACS URL to that path, which is a manual IdP-side step this migration
cannot perform.
"""

from __future__ import annotations

import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.utils.encryption import encrypt_string_to_bytes

# revision identifiers, used by Alembic.
revision = "c8d1a4b7e920"
down_revision = "1fc2904131a3"
branch_labels = None
depends_on = None

_SAML_PROVIDER_NAME = "saml"


def _sso_provider_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "sso_provider",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("display_name", sa.String),
        sa.Column("provider_type", sa.String),
        sa.Column("config", sa.LargeBinary),
        sa.Column("allowed_email_domains", postgresql.ARRAY(sa.String)),
        sa.Column("enabled", sa.Boolean),
    )


def _saml_config_from_conf_dir() -> dict[str, str] | None:
    """Read the legacy settings.json (and optional certs/sp.key) into the
    per-type config shape. Returns None when the file is absent or missing a
    required IdP field, so a half-configured directory is skipped."""
    from onyx.configs.app_configs import SAML_CONF_DIR

    conf_dir = Path(SAML_CONF_DIR)
    try:
        raw = json.loads((conf_dir / "settings.json").read_text())
    except (OSError, ValueError):
        return None

    idp = raw.get("idp") or {}
    sp = raw.get("sp") or {}
    sso = idp.get("singleSignOnService") or {}
    config: dict[str, str] = {
        "idp_entity_id": idp.get("entityId") or "",
        "idp_sso_url": sso.get("url") or "",
        "idp_x509_cert": idp.get("x509cert") or "",
        "sp_entity_id": sp.get("entityId") or "",
    }
    if not all(config.values()):
        return None

    sp_cert = sp.get("x509cert")
    if sp_cert:
        config["sp_x509_cert"] = sp_cert
    try:
        sp_key = (conf_dir / "certs" / "sp.key").read_text().strip()
        if sp_key:
            config["sp_private_key"] = sp_key
    except OSError:
        pass
    return config


def _import_saml(table: sa.Table) -> None:
    from onyx.configs.app_configs import AUTH_TYPE
    from onyx.configs.app_configs import VALID_EMAIL_DOMAINS
    from onyx.configs.constants import AuthType
    from shared_configs.configs import MULTI_TENANT

    # Cloud auth is centralized, and only a single-SAML instance has a
    # SAML_CONF_DIR worth importing.
    if MULTI_TENANT or AUTH_TYPE != AuthType.SAML:
        return

    bind = op.get_bind()
    if bind.execute(
        sa.select(table.c.id).where(table.c.provider_type == "SAML").limit(1)
    ).first():
        return

    config = _saml_config_from_conf_dir()
    if config is None:
        return

    bind.execute(
        table.insert().values(
            name=_SAML_PROVIDER_NAME,
            display_name="SAML SSO",
            provider_type="SAML",
            # Same encoding as the EncryptedJson ORM column: JSON, then encrypt.
            config=encrypt_string_to_bytes(json.dumps(config)),
            allowed_email_domains=[d.lower() for d in VALID_EMAIL_DOMAINS],
            enabled=True,
        )
    )


def upgrade() -> None:
    metadata = sa.MetaData()
    _import_saml(_sso_provider_table(metadata))


def downgrade() -> None:
    # No-op. The imported row may have been edited through the provider store
    # since the upgrade, so deleting it would drop operator changes (IdP
    # settings, signing material, domains). Seeded data is not cleanly
    # reversible, so the row is left in place.
    pass
