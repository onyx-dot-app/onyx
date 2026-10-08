"""Background-only installation identity, independent of application DB pools."""

import re
import secrets

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.pool import NullPool

from onyx.configs.app_configs import USE_IAM_AUTH
from onyx.db.engine.iam_auth import provide_iam_token
from onyx.db.engine.pg_ssl import pg_ssl_psycopg2_connect_args
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.utils.variable_functionality import global_version, is_ee_available
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def edition_selected() -> bool:
    """Whether this process has selected its edition. Spawned indexing children
    select it after startup, from their parent's arguments."""
    return global_version.is_ee_version() or not is_ee_available()


def installation_seed() -> bytes:
    if not edition_selected():
        # Each process caches its secret codec on first use. Decrypting before the
        # process selects its edition would pin the Community codec for every later
        # credential decrypt in that process.
        raise RuntimeError("Process edition is not selected yet")

    from onyx.db.models import EncryptedKeyValueStore

    # Use the application's encrypted store and credentials only for this one row.
    # Collectors use a separate read-only connection for all subsequent source reads.
    engine = create_engine(
        build_connection_string(db_api=SYNC_DB_API),
        poolclass=NullPool,
        connect_args={
            **pg_ssl_psycopg2_connect_args(),
            "connect_timeout": 2,
            "application_name": "onyx_fleet_enrollment",
            "options": "-c statement_timeout=1500 -c lock_timeout=100",
        },
        execution_options={"schema_translate_map": {None: POSTGRES_DEFAULT_SCHEMA}},
    )
    if USE_IAM_AUTH:
        event.listen(engine, "do_connect", provide_iam_token)
    key = "fleet_telemetry_installation_seed_v1"
    try:
        with engine.begin() as connection:
            # First read avoids rewriting a secret on every process restart.
            statement = select(EncryptedKeyValueStore.value).where(
                EncryptedKeyValueStore.key == key
            )
            value = connection.execute(statement).scalar_one_or_none()
            if value is None:
                connection.execute(
                    insert(EncryptedKeyValueStore)
                    .values(key=key, value={"seed": secrets.token_hex(32)})
                    .on_conflict_do_nothing(index_elements=["key"])
                )
                value = connection.execute(statement).scalar_one()
            seed = value.get_value(apply_mask=False).get("seed")
            if not isinstance(seed, str) or not re.fullmatch(r"[a-f0-9]{64}", seed):
                raise ValueError("Invalid fleet installation identity")
            return bytes.fromhex(seed)
    finally:
        engine.dispose()
