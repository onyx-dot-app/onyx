"""normalize llm provider custom config api keys

Revision ID: 39178a00fbec
Revises: bd38e2a494ff
Create Date: 2026-07-15 17:53:59.646319

Moves generic ``<PROVIDER>_API_KEY`` / ``<PROVIDER>_API_BASE`` entries out of
``llm_provider.custom_config`` and into the first-class ``api_key`` /
``api_base`` columns when those are unset. Historically such entries only
worked by being injected into ``os.environ`` at call time; the columns are the
supported path now that env injection is disabled on multi-tenant deployments.
Keys with no column equivalent are intentionally left in place.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import table

from onyx.utils.encryption import encrypt_string_to_bytes

# revision identifiers, used by Alembic.
revision = "39178a00fbec"
down_revision = "bd38e2a494ff"
branch_labels = None
depends_on = None


def _normalize(value: str) -> str:
    return value.upper().replace("_", "").replace("-", "")


def upgrade() -> None:
    connection = op.get_bind()

    llm_table = table(
        "llm_provider",
        sa.Column("id", sa.Integer()),
        sa.Column("provider", sa.String()),
        sa.Column("api_key", sa.LargeBinary()),
        sa.Column("api_base", sa.String()),
        sa.Column("custom_config", postgresql.JSONB()),
    )

    rows = connection.execute(
        sa.select(llm_table).where(llm_table.c.custom_config.isnot(None))
    )

    for row in rows:
        custom_config = row.custom_config
        if not isinstance(custom_config, dict) or not custom_config:
            continue

        provider_normalized = _normalize(row.provider or "")
        if not provider_normalized:
            continue

        new_config = dict(custom_config)
        new_api_key: bytes | None = None
        new_api_base: str | None = None

        for key, value in custom_config.items():
            if not isinstance(value, str) or not value:
                continue
            key_normalized = _normalize(key)
            if (
                key_normalized == f"{provider_normalized}APIKEY"
                and row.api_key is None
                and new_api_key is None
            ):
                new_api_key = encrypt_string_to_bytes(value)
                del new_config[key]
            elif (
                key_normalized == f"{provider_normalized}APIBASE"
                and not row.api_base
                and new_api_base is None
            ):
                new_api_base = value
                del new_config[key]

        if new_api_key is None and new_api_base is None:
            continue

        values: dict[str, object] = {"custom_config": new_config}
        if new_api_key is not None:
            values["api_key"] = new_api_key
        if new_api_base is not None:
            values["api_base"] = new_api_base

        connection.execute(
            llm_table.update().where(llm_table.c.id == row.id).values(**values)
        )


def downgrade() -> None:
    # The moved values remain fully functional in the api_key / api_base
    # columns on older code (explicit params always won over env vars), so
    # there is nothing to restore.
    pass
