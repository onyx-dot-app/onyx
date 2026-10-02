"""move atlassian scoped_token from connector configs to credentials

Whether an Atlassian API token has scopes is a property of the token, so it now
lives on the credential (`credential_json.scoped_token`) instead of each
Confluence or Jira connector's config. A credential linked to a connector whose
config said `scoped_token: true` gets the flag; then the key leaves every
Confluence and Jira connector config, whose typed configs no longer accept it.

Credentials are encrypted, so this goes through ``onyx.utils.encryption`` as
revision ``1e0a3e4226f7`` does.

Revision ID: e4283ce70fbd
Revises: b3e7c1d9a4f2
Create Date: 2026-10-02 21:00:00.000000

"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.encryption import encrypt_string_to_bytes

# revision identifiers, used by Alembic.
revision = "e4283ce70fbd"
down_revision = "b3e7c1d9a4f2"
branch_labels = None
depends_on = None


ATLASSIAN_SOURCES = ("CONFLUENCE", "JIRA")
SCOPED_TOKEN_KEY = "scoped_token"


def _set_credential_flag(bind: sa.engine.Connection, credential_id: int) -> None:
    row = bind.execute(
        sa.text("SELECT credential_json FROM credential WHERE id = :id"),
        {"id": credential_id},
    ).first()
    if row is None or row.credential_json is None:
        return
    credential_json = json.loads(decrypt_bytes_to_string(bytes(row.credential_json)))
    if credential_json.get(SCOPED_TOKEN_KEY) is True:
        return
    credential_json[SCOPED_TOKEN_KEY] = True
    bind.execute(
        sa.text("UPDATE credential SET credential_json = :value WHERE id = :id"),
        {
            "value": encrypt_string_to_bytes(json.dumps(credential_json)),
            "id": credential_id,
        },
    )


def upgrade() -> None:
    bind = op.get_bind()

    # Every credential linked to a connector that said its token has scopes.
    # A credential shared with an unscoped connector still gets the flag: the
    # token itself is either scoped or not.
    credential_ids = bind.execute(
        sa.text(
            """
            SELECT DISTINCT ccp.credential_id
            FROM connector c
            JOIN connector_credential_pair ccp ON ccp.connector_id = c.id
            WHERE c.source IN :sources
              AND c.connector_specific_config ->> :key = 'true'
            """
        ).bindparams(sa.bindparam("sources", expanding=True)),
        {"sources": list(ATLASSIAN_SOURCES), "key": SCOPED_TOKEN_KEY},
    ).scalars()
    for credential_id in credential_ids.all():
        _set_credential_flag(bind, credential_id)

    connector = sa.table(
        "connector",
        sa.column("source", sa.String),
        sa.column("connector_specific_config", postgresql.JSONB),
    )
    op.execute(
        connector.update()
        .where(
            connector.c.source.in_(ATLASSIAN_SOURCES),
            connector.c.connector_specific_config.has_key(SCOPED_TOKEN_KEY),
        )
        .values(
            connector_specific_config=connector.c.connector_specific_config.op("-")(
                sa.cast(SCOPED_TOKEN_KEY, sa.Text)
            )
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Put the flag back on each connector linked to a scoped credential. The
    # credentials keep their key, which the older code ignores.
    rows = bind.execute(
        sa.text(
            """
            SELECT ccp.connector_id, c.credential_json
            FROM connector_credential_pair ccp
            JOIN credential c ON c.id = ccp.credential_id
            JOIN connector conn ON conn.id = ccp.connector_id
            WHERE conn.source IN :sources
              AND c.credential_json IS NOT NULL
            """
        ).bindparams(sa.bindparam("sources", expanding=True)),
        {"sources": list(ATLASSIAN_SOURCES)},
    ).all()
    scoped_connector_ids = {
        row.connector_id
        for row in rows
        if json.loads(decrypt_bytes_to_string(bytes(row.credential_json))).get(
            SCOPED_TOKEN_KEY
        )
        is True
    }
    for connector_id in scoped_connector_ids:
        bind.execute(
            sa.text(
                """
                UPDATE connector
                SET connector_specific_config =
                    connector_specific_config || '{"scoped_token": true}'::jsonb
                WHERE id = :id
                """
            ),
            {"id": connector_id},
        )
