"""Provision Onyx-managed built-in external apps for existing tenants (cloud only)

Backfills the built-in external apps (Slack, Linear, GitHub, Gmail, Google
Calendar, Google Drive, HubSpot) for tenants created before those apps existed,
matching what tenant-creation provisioning seeds.

Cloud only: in multi-tenant mode Alembic invokes this once per tenant schema
(the env sets search_path per schema). In self-hosted single-tenant mode it is a
no-op. Every existing external app is deleted first (clean slate), then the full
catalog is re-created (disabled) with credentials sourced from the populated
``EXT_APP_<APP_TYPE>_<FIELD>`` env vars. Re-seeding this way also clears any
admin enabled-state and per-action policy overrides on the built-in apps.

Self-contained by design: the app catalog, env parsing, and credential
encryption are inlined rather than imported from application code, so the
migration stays reproducible and independent of code that may change later. The
catalog below is a frozen 2026-06 snapshot of ``onyx/external_apps/providers/*``;
the encryption mirrors ``onyx.utils.encryption._encrypt_string``.

Revision ID: f3a9c1d4b7e2
Revises: 8f2c4a1d9e3b
Create Date: 2026-06-22 00:00:00.000000

"""

import json
import logging
import os
import uuid
from os import urandom

import sqlalchemy as sa
from alembic import op
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import modes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f3a9c1d4b7e2"
down_revision = "8f2c4a1d9e3b"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# Frozen snapshot of the Onyx-managed built-in app catalog. Every managed app
# authenticates the upstream with a bearer access token and is keyed in env by
# EXT_APP_<APP_TYPE>_CLIENT_ID / _CLIENT_SECRET.
_AUTH_TEMPLATE = {"Authorization": "Bearer {access_token}"}
_CRED_FIELDS = ("client_id", "client_secret")
_BUILT_IN_APPS: list[dict] = [
    {
        "app_type": "SLACK",
        "slug": "slack",
        "name": "Slack",
        "description": (
            "Read your Slack messages and channels as context inside Onyx Craft."
        ),
        "upstream_url_patterns": ["https://slack\\.com/api/.*"],
    },
    {
        "app_type": "GOOGLE_CALENDAR",
        "slug": "google-calendar",
        "name": "Google Calendar",
        "description": (
            "Read and create events on your Google Calendar from inside Onyx Craft."
        ),
        "upstream_url_patterns": ["https://www\\.googleapis\\.com/calendar/.*"],
    },
    {
        "app_type": "GOOGLE_DRIVE",
        "slug": "google-drive",
        "name": "Google Drive",
        "description": (
            "Search, read, create, and edit files and Google Docs in your Google "
            "Drive inside Onyx Craft."
        ),
        "upstream_url_patterns": [
            "https://www\\.googleapis\\.com/drive/.*",
            "https://www\\.googleapis\\.com/upload/drive/.*",
            "https://docs\\.googleapis\\.com/.*",
        ],
    },
    {
        "app_type": "GMAIL",
        "slug": "gmail",
        "name": "Gmail",
        "description": (
            "Read, search, send, and draft email from your Gmail account inside "
            "Onyx Craft."
        ),
        "upstream_url_patterns": ["https://gmail\\.googleapis\\.com/gmail/.*"],
    },
    {
        "app_type": "LINEAR",
        "slug": "linear",
        "name": "Linear",
        "description": (
            "Read and create issues, projects, and comments in Linear on the "
            "user's behalf."
        ),
        "upstream_url_patterns": ["https://api\\.linear\\.app/.*"],
    },
    {
        "app_type": "GITHUB",
        "slug": "github",
        "name": "GitHub",
        "description": (
            "Read repositories, issues, and pull requests, open new issues, and "
            "add comments in GitHub on the user's behalf."
        ),
        "upstream_url_patterns": ["https://api\\.github\\.com/.*"],
    },
    {
        "app_type": "HUBSPOT",
        "slug": "hubspot",
        "name": "HubSpot",
        "description": (
            "Read and manage HubSpot CRM contacts, companies, and deals "
            "on the user's behalf."
        ),
        "upstream_url_patterns": ["https://api\\.hubapi\\.com/.*"],
    },
]


def _trimmed_key(key: str) -> bytes:
    encoded = key.encode()
    for size in (32, 24, 16):
        if len(encoded) >= size:
            return encoded[:size]
    raise RuntimeError("Invalid ENCRYPTION_KEY_SECRET - too short")


def _encrypt(raw: str) -> bytes:
    """AES-CBC (PKCS7, random IV prepended), matching the EE encryption used by
    the EncryptedJson column. Falls back to plaintext bytes when no key is set,
    matching the MIT path — though in practice this only runs in the cloud."""
    key = os.environ.get("ENCRYPTION_KEY_SECRET") or ""
    if not key:
        return raw.encode()
    iv = urandom(16)
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(raw.encode()) + padder.finalize()
    cipher = Cipher(algorithms.AES(_trimmed_key(key)), modes.CBC(iv))
    encryptor = cipher.encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


def _org_credentials(app_type: str) -> dict[str, str]:
    """Credentials from EXT_APP_<APP_TYPE>_<FIELD> env vars. All-or-nothing:
    partial config is treated as unconfigured (stored as an empty mapping)."""
    creds = {
        field: os.environ.get(f"EXT_APP_{app_type}_{field.upper()}", "").strip()
        for field in _CRED_FIELDS
    }
    return creds if all(creds.values()) else {}


def _is_cloud() -> bool:
    """External apps are seeded only in the managed cloud (multi-tenant)
    deployment; self-hosted installs manage their own apps."""
    return os.environ.get("MULTI_TENANT", "").lower() == "true"


def upgrade() -> None:
    if not _is_cloud():
        return

    bind = op.get_bind()

    # Clean slate: delete every existing external app so the rows seeded below
    # always match the current frozen catalog (config / URL patterns / auth /
    # credentials) rather than whatever a prior seed left. Deleting the backing
    # skill cascades to the external_app row and its policies + credentials.
    # Cloud blocks admin-created (CUSTOM) apps, so the only rows here are these
    # built-ins.
    bind.execute(
        sa.text("DELETE FROM skill WHERE id IN (SELECT skill_id FROM external_app)")
    )

    insert_skill = sa.text(
        "INSERT INTO skill "
        "(id, slug, name, description, built_in_skill_id, "
        " bundle_file_id, bundle_sha256, author_user_id, is_public, enabled) "
        "VALUES (:id, :slug, :name, :description, :slug, "
        " NULL, NULL, NULL, TRUE, FALSE)"
    ).bindparams(sa.bindparam("id", type_=postgresql.UUID(as_uuid=True)))

    insert_app = sa.text(
        "INSERT INTO external_app "
        "(skill_id, app_type, upstream_url_patterns, auth_template, "
        " organization_credentials) "
        "VALUES (:skill_id, :app_type, :patterns, :auth, :creds)"
    ).bindparams(
        sa.bindparam("skill_id", type_=postgresql.UUID(as_uuid=True)),
        sa.bindparam("patterns", type_=postgresql.ARRAY(sa.String())),
        sa.bindparam("auth", type_=postgresql.JSONB()),
        sa.bindparam("creds", type_=sa.LargeBinary()),
    )

    created = 0
    for app in _BUILT_IN_APPS:
        app_type = app["app_type"]
        # An orphan built-in skill (unique slug, no external_app) can survive the
        # delete above; reuse it rather than collide on the unique slug.
        existing_skill = bind.execute(
            sa.text("SELECT id FROM skill WHERE slug = :slug"),
            {"slug": app["slug"]},
        ).scalar()
        if existing_skill is not None:
            skill_id = existing_skill
        else:
            skill_id = uuid.uuid4()
            bind.execute(
                insert_skill,
                {
                    "id": skill_id,
                    "slug": app["slug"],
                    "name": app["name"],
                    "description": app["description"],
                },
            )

        bind.execute(
            insert_app,
            {
                "skill_id": skill_id,
                "app_type": app_type,
                "patterns": app["upstream_url_patterns"],
                "auth": _AUTH_TEMPLATE,
                "creds": _encrypt(json.dumps(_org_credentials(app_type))),
            },
        )
        created += 1

    logger.info("Built-in app backfill: created %s app(s) for this schema.", created)


def downgrade() -> None:
    if not _is_cloud():
        return

    # Undo only what this migration seeds: the built-in app types in the catalog
    # above. Scoping by app_type leaves any other external app (e.g. a CUSTOM
    # one) untouched. Deleting the backing skill cascades to the external_app row
    # and its policies/credentials.
    built_in_types = [app["app_type"] for app in _BUILT_IN_APPS]
    op.get_bind().execute(
        sa.text(
            "DELETE FROM skill WHERE id IN ("
            "SELECT skill_id FROM external_app WHERE app_type = ANY(:types))"
        ).bindparams(sa.bindparam("types", type_=postgresql.ARRAY(sa.String()))),
        {"types": built_in_types},
    )
