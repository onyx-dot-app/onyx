"""Physical database ("shard") registry for tenant routing.

Onyx addresses a tenant by *schema* via ``schema_translate_map``. This module adds
the orthogonal axis: which *database* that schema lives in.

Design notes:

- The default shard's engine is owned by :class:`onyx.db.engine.sql_engine.SqlEngine`,
  not by this module. That keeps the ~20 existing ``init_engine`` call sites and the
  single-database deployment path completely unchanged.
- Non-default shard engines are created lazily here, on first use, mirroring the pool
  configuration the default engine was initialized with.
- With no ``ONYX_DB_SHARDS`` configured there is exactly one shard and this module is
  a thin pass-through to ``SqlEngine``.

Connection budget: the *total* pool across shards is held roughly constant rather than
multiplied per shard — see ``shard_pool_divisor``. Multiplying it would put N times the
connection load on the database/pooler, which is how this deployment has hurt itself
before.
"""

import json
import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine, create_engine

from onyx.configs.app_configs import (
    ONYX_DB_CATALOG_SHARD,
    ONYX_DB_DEFAULT_SHARD,
    ONYX_DB_SHARDS_JSON,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ShardConfigurationError(RuntimeError):
    """Raised when ONYX_DB_SHARDS is malformed or references an unknown shard."""


@dataclass(frozen=True)
class ShardSpec:
    """Connection coordinates for one physical database."""

    name: str
    host: str
    port: str
    db: str
    user: str
    password: str

    def describe(self) -> str:
        """Loggable identity — never includes the password."""
        return f"{self.name}({self.user}@{self.host}:{self.port}/{self.db})"


def _parse_shard_specs() -> dict[str, ShardSpec]:
    """Build the shard table from configuration.

    The default shard always exists and is derived from the POSTGRES_* settings, so
    an unconfigured deployment gets exactly one shard.
    """
    default_spec = ShardSpec(
        name=ONYX_DB_DEFAULT_SHARD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        db=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )
    specs: dict[str, ShardSpec] = {default_spec.name: default_spec}

    if not ONYX_DB_SHARDS_JSON:
        return specs

    try:
        raw = json.loads(ONYX_DB_SHARDS_JSON)
    except json.JSONDecodeError as e:
        raise ShardConfigurationError(f"ONYX_DB_SHARDS is not valid JSON: {e}") from e

    if not isinstance(raw, dict):
        raise ShardConfigurationError(
            f"ONYX_DB_SHARDS must be a JSON object of shard name -> overrides, got {type(raw).__name__}"
        )

    for name, overrides in raw.items():
        if not isinstance(overrides, dict):
            raise ShardConfigurationError(
                f"ONYX_DB_SHARDS['{name}'] must be an object of connection overrides"
            )
        unknown = set(overrides) - {"host", "port", "db", "user", "password"}
        if unknown:
            raise ShardConfigurationError(
                f"ONYX_DB_SHARDS['{name}'] has unknown keys: {sorted(unknown)}"
            )
        specs[name] = ShardSpec(
            name=name,
            host=str(overrides.get("host", POSTGRES_HOST)),
            port=str(overrides.get("port", POSTGRES_PORT)),
            db=str(overrides.get("db", POSTGRES_DB)),
            user=str(overrides.get("user", POSTGRES_USER)),
            password=str(overrides.get("password", POSTGRES_PASSWORD)),
        )

    if ONYX_DB_CATALOG_SHARD not in specs:
        raise ShardConfigurationError(
            f"ONYX_DB_CATALOG_SHARD='{ONYX_DB_CATALOG_SHARD}' is not a configured shard "
            f"(known: {sorted(specs)})"
        )

    return specs


_SHARD_SPECS: dict[str, ShardSpec] | None = None
_SPECS_LOCK = threading.Lock()


def get_shard_specs() -> dict[str, ShardSpec]:
    """All configured shards, keyed by name. Parsed once per process."""
    global _SHARD_SPECS
    if _SHARD_SPECS is None:
        with _SPECS_LOCK:
            if _SHARD_SPECS is None:
                _SHARD_SPECS = _parse_shard_specs()
                if len(_SHARD_SPECS) > 1:
                    logger.info(
                        "Tenant sharding enabled across %d databases: %s",
                        len(_SHARD_SPECS),
                        ", ".join(s.describe() for s in _SHARD_SPECS.values()),
                    )
    return _SHARD_SPECS


def reset_shard_specs() -> None:
    """Re-read the shard table from configuration, disposing engines built from the old one.

    Mirrors ``SqlEngine.reset_engine``. Needed anywhere shard configuration can change
    within a process — tests, and forked children that re-read their environment.
    """
    global _SHARD_SPECS
    ShardRegistry.reset()
    with _SPECS_LOCK:
        _SHARD_SPECS = None


def shard_pool_divisor() -> int:
    """Divisor applied to per-engine pool sizes so the total stays bounded.

    With a single shard this is 1, i.e. pool sizing is exactly as it has always been.
    """
    return max(1, len(get_shard_specs()))


def is_default_shard(shard_name: str) -> bool:
    return shard_name == ONYX_DB_DEFAULT_SHARD


def get_default_shard_name() -> str:
    return ONYX_DB_DEFAULT_SHARD


def get_catalog_shard_name() -> str:
    return ONYX_DB_CATALOG_SHARD


class ShardRegistry:
    """Lazily-created engines for non-default shards.

    The default shard is deliberately absent from ``_engines``; requests for it are
    delegated to ``SqlEngine`` so there is exactly one default engine per process.
    """

    _engines: dict[str, Engine] = {}
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_engine(cls, shard_name: str) -> Engine:
        # Imported here: sql_engine imports this module for pool sizing.
        from onyx.db.engine.sql_engine import SqlEngine

        if is_default_shard(shard_name):
            return SqlEngine.get_engine()

        engine = cls._engines.get(shard_name)
        if engine is not None:
            return engine

        with cls._lock:
            # Re-check: another thread may have built it while we waited.
            engine = cls._engines.get(shard_name)
            if engine is not None:
                return engine

            specs = get_shard_specs()
            spec = specs.get(shard_name)
            if spec is None:
                raise ShardConfigurationError(
                    f"No configuration for shard '{shard_name}' (known: {sorted(specs)})"
                )

            engine = cls._build_engine(spec)
            cls._engines[shard_name] = engine
            logger.info("Created engine for shard %s", spec.describe())
            return engine

    @classmethod
    def _build_engine(cls, spec: ShardSpec) -> Engine:
        """Build a shard engine mirroring the default engine's pool configuration."""
        from onyx.db.engine.sql_engine import (
            SYNC_DB_API,
            SqlEngine,
            build_connection_string,
            provide_iam_token,
        )

        profile = SqlEngine.get_engine_profile()

        connection_string = build_connection_string(
            db_api=SYNC_DB_API,
            user=spec.user,
            password=spec.password,
            host=spec.host,
            port=spec.port,
            db=spec.db,
            app_name=f"{SqlEngine.get_app_name()}_sync_{spec.name}",
            use_iam_auth=profile.use_iam,
        )

        engine_kwargs: dict[str, Any] = dict(profile.engine_kwargs)
        engine = create_engine(connection_string, **engine_kwargs)

        if profile.use_iam:
            event.listen(engine, "do_connect", provide_iam_token)

        return engine

    @classmethod
    def reset(cls) -> None:
        """Dispose every non-default shard engine.

        Must be called anywhere ``SqlEngine.reset_engine()`` is called — notably in
        forked child processes, which inherit unusable parent connections.
        """
        with cls._lock:
            for name, engine in cls._engines.items():
                try:
                    engine.dispose()
                except Exception:
                    logger.warning("Failed disposing engine for shard %s", name)
            cls._engines = {}


def get_shard_spec(shard_name: str) -> ShardSpec:
    """Connection coordinates for one shard.

    For callers that need to reach a shard without going through an ``Engine`` —
    notably Alembic, which wants a URL string.
    """
    specs = get_shard_specs()
    spec = specs.get(shard_name)
    if spec is None:
        raise ShardConfigurationError(
            f"No configuration for shard '{shard_name}' (known: {sorted(specs)})"
        )
    return spec


def get_engine_for_shard(shard_name: str) -> Engine:
    return ShardRegistry.get_engine(shard_name)


def get_catalog_engine() -> Engine:
    """Engine for the database holding the shared `public` catalog tables."""
    return ShardRegistry.get_engine(ONYX_DB_CATALOG_SHARD)
