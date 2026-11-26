"""convert URL-pattern apps to REST apps

Revision ID: 933a21d46472
Revises: d04326aae2f9
Create Date: 2026-11-26 12:00:00.000000

A URL-pattern app (a CUSTOM external_app) with one pattern of the form
`https://host/path/*` becomes a REST app with the base URL
`https://host/path` and no endpoints. The integration row stays, so its agent
links, shares, sign-ins, policies and task links stay. The integration gets
an api_app row and, for one release, the tool row that the previous release
reads. The external_app row stays: its gated_app row holds old approvals.

An app with other patterns stays a URL-pattern app: no single base URL
covers the same URLs.
"""

import json
import re

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "933a21d46472"
down_revision = "d04326aae2f9"
branch_labels = None
depends_on = None

# The host of a pattern is literal; only the `/*` at the end is a wildcard.
_PREFIX_PATTERN = re.compile(r"(https?://[^/*]+(?:/[^*]*)?)/\*")

_SELECT_URL_PATTERN_APPS = """
    SELECT i.id, i.name, i.description, i.owner_user_id, e.upstream_url_patterns
    FROM integration i
    JOIN external_app e ON e.id = i.external_app_id
    WHERE e.app_type = 'CUSTOM'
    ORDER BY i.id
"""

_INSERT_TOOL = """
    INSERT INTO tool (name, description, display_name, openapi_schema,
        custom_headers, user_id, passthrough_auth, enabled)
    VALUES (:name, :description, :name, CAST(:document AS jsonb), '[]',
        :user_id, false, true)
    RETURNING id
"""

_INSERT_API_APP = """
    INSERT INTO api_app (api_type, base_url, openapi_document, graphql_schema)
    VALUES ('rest', :base_url, :document, NULL)
    RETURNING id
"""

_RELINK_INTEGRATION = """
    UPDATE integration
    SET external_app_id = NULL, tool_id = :tool_id, api_app_id = :api_app_id
    WHERE id = :id
"""

# A REST app stores only its endpoints; a request to no endpoint is the
# other-request action, under the same key, so its policies still apply.
_DELETE_OTHER_REQUEST_ACTION = """
    DELETE FROM integration_action
    WHERE integration_id = :id AND key = 'unspecified'
"""


def _spec(name: str, description: str | None, base_url: str) -> dict:
    """The document the admin page saves for a REST app with no endpoints."""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": name,
            "description": description or name,
            "version": "1.0.0",
        },
        "servers": [{"url": base_url}],
        "paths": {},
    }


def upgrade() -> None:
    bind = op.get_bind()
    for id_, name, description, owner_user_id, patterns in bind.execute(
        sa.text(_SELECT_URL_PATTERN_APPS)
    ).all():
        match = (
            _PREFIX_PATTERN.fullmatch(patterns[0].strip())
            if len(patterns) == 1
            else None
        )
        if match is None:
            continue
        base_url = match.group(1)
        document = json.dumps(_spec(name, description, base_url))
        tool_id = bind.execute(
            sa.text(_INSERT_TOOL),
            {
                "name": name,
                "description": description,
                "document": document,
                "user_id": owner_user_id,
            },
        ).scalar_one()
        api_app_id = bind.execute(
            sa.text(_INSERT_API_APP), {"base_url": base_url, "document": document}
        ).scalar_one()
        bind.execute(
            sa.text(_RELINK_INTEGRATION),
            {"id": id_, "tool_id": tool_id, "api_app_id": api_app_id},
        )
        bind.execute(sa.text(_DELETE_OTHER_REQUEST_ACTION), {"id": id_})


def downgrade() -> None:
    # A converted app is a REST app, which the previous release reads from its
    # tool row.
    pass
