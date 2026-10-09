"""backfill legacy_callback on seeded sso rows

Revision ID: 8f3b2c91d4e7
Revises: d396075958bd
Create Date: 2026-07-16 15:30:00.000000

"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.encryption import encrypt_string_to_bytes

# revision identifiers, used by Alembic.
revision = "8f3b2c91d4e7"
down_revision = "d396075958bd"
branch_labels = None
depends_on = None

# The names 1fc2904131a3's seed assigned. Rows created through the admin API
# are matched only when their client_id equals the env credential the seed
# copied, so an operator-authored row with its own IdP client is never touched.
_SEEDED_NAMES = ("google", "openid")


def upgrade() -> None:
    """Stamp legacy_callback=true onto rows the 1fc2904131a3 seed created
    before the flag existed, so their flows keep sending the redirect URI the
    deployment's IdP client already allowlists.

    Matches on the seeded name plus the still-present env client_id. A
    deployment that already removed its env credentials has either registered
    the parametric URI or reconfigured, and flipping it here could break it.
    """
    from onyx.configs.app_configs import OAUTH_CLIENT_ID
    from shared_configs.configs import MULTI_TENANT

    if MULTI_TENANT:
        return

    # Resolve the credential exactly as the 1fc2904131a3 seed did, so the
    # match sees the same value the seed stored.
    env_client_id = OAUTH_CLIENT_ID
    if not env_client_id:
        return

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, config FROM sso_provider WHERE name IN :names").bindparams(
            sa.bindparam("names", expanding=True)
        ),
        {"names": list(_SEEDED_NAMES)},
    ).fetchall()

    for row_id, config_bytes in rows:
        config = json.loads(decrypt_bytes_to_string(bytes(config_bytes)))
        if config.get("client_id") != env_client_id:
            continue
        if config.get("legacy_callback"):
            continue
        config["legacy_callback"] = True
        bind.execute(
            sa.text("UPDATE sso_provider SET config = :config WHERE id = :id"),
            {"config": encrypt_string_to_bytes(json.dumps(config)), "id": row_id},
        )


def downgrade() -> None:
    # The flag is additive and validated as optional. Leaving it in place on
    # downgrade is harmless.
    pass
