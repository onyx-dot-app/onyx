"""Backfill the Jira built-in external app for existing tenants (cloud only)

Seeds Jira (disabled) per tenant schema with credentials from the
``EXT_APP_JIRA_*`` env vars, following ``2e0b2b146de1``: frozen snapshot
of ``onyx/external_apps/providers/jira.py``, no-op when not multi-tenant.

Revision ID: cc12d9496945
Revises: bd38e2a494ff
Create Date: 2026-07-15 18:13:18.797112

"""

import json
import os
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from onyx.utils.encryption import encrypt_string_to_bytes

# revision identifiers, used by Alembic.
revision = "cc12d9496945"
down_revision = "bd38e2a494ff"
branch_labels = None
depends_on = None

_APP_TYPE = "JIRA"
_SLUG = "jira"
_NAME = "Jira"
_DESCRIPTION = (
    "Search, read, and write Jira issues, projects, comments, and "
    "transitions on the user's behalf."
)
_UPSTREAM_URL_PATTERNS = ["https://api\\.atlassian\\.com/.*"]
_AUTH_TEMPLATE = {"Authorization": "Bearer {access_token}"}
_CRED_FIELDS = ("client_id", "client_secret")


def _org_credentials() -> dict[str, str]:
    creds = {
        field: os.environ.get(f"EXT_APP_{_APP_TYPE}_{field.upper()}", "").strip()
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

    # Deleting the skill cascades to its external_app + policies/credentials.
    bind.execute(
        sa.text(
            "DELETE FROM skill WHERE slug = :slug OR id IN "
            "(SELECT skill_id FROM external_app WHERE app_type = :app_type)"
        ),
        {"slug": _SLUG, "app_type": _APP_TYPE},
    )

    skill_id = uuid.uuid4()
    bind.execute(
        sa.text(
            "INSERT INTO skill "
            "(id, slug, name, description, built_in_skill_id, "
            " bundle_file_id, bundle_sha256, author_user_id, "
            " public_permission, enabled) "
            "VALUES (:id, :slug, :name, :description, :slug, "
            " NULL, NULL, NULL, 'VIEWER', FALSE)"
        ).bindparams(sa.bindparam("id", type_=postgresql.UUID(as_uuid=True))),
        {
            "id": skill_id,
            "slug": _SLUG,
            "name": _NAME,
            "description": _DESCRIPTION,
        },
    )

    bind.execute(
        sa.text(
            "INSERT INTO external_app "
            "(skill_id, app_type, upstream_url_patterns, auth_template, "
            " organization_credentials) "
            "VALUES (:skill_id, :app_type, :patterns, :auth, :creds)"
        ).bindparams(
            sa.bindparam("skill_id", type_=postgresql.UUID(as_uuid=True)),
            sa.bindparam("patterns", type_=postgresql.ARRAY(sa.String())),
            sa.bindparam("auth", type_=postgresql.JSONB()),
            sa.bindparam("creds", type_=sa.LargeBinary()),
        ),
        {
            "skill_id": skill_id,
            "app_type": _APP_TYPE,
            "patterns": _UPSTREAM_URL_PATTERNS,
            "auth": _AUTH_TEMPLATE,
            "creds": encrypt_string_to_bytes(json.dumps(_org_credentials())),
        },
    )


def downgrade() -> None:
    if not _is_cloud():
        return

    op.get_bind().execute(
        sa.text(
            "DELETE FROM skill WHERE id IN "
            "(SELECT skill_id FROM external_app WHERE app_type = :app_type)"
        ),
        {"app_type": _APP_TYPE},
    )
