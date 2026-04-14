import os
import re
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy import pool
from sqlalchemy.engine import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DB_READONLY_PASSWORD
from onyx.configs.app_configs import DB_READONLY_USER
from onyx.configs.app_configs import LOG_POSTGRES_CONN_COUNTS
from onyx.configs.app_configs import LOG_POSTGRES_LATENCY
from onyx.configs.app_configs import POSTGRES_DB
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_HOSTS
from onyx.configs.app_configs import POSTGRES_PASSWORD
from onyx.configs.app_configs import POSTGRES_POOL_PRE_PING
from onyx.configs.app_configs import POSTGRES_POOL_RECYCLE
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USE_NULL_POOL
from onyx.configs.app_configs import POSTGRES_USER
from onyx.configs.constants import POSTGRES_UNKNOWN_APP_NAME
from onyx.db.engine.iam_auth import provide_iam_token
from onyx.server.utils import BasicAuthenticationError
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()


SCHEMA_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


def is_valid_schema_name(name: str) -> bool:
    return SCHEMA_NAME_REGEX.match(name) is not None


SYNC_DB_API = "psycopg2"
ASYNC_DB_API = "asyncpg"

USE_IAM_AUTH = os.getenv("USE_IAM_AUTH", "False").lower() == "true"


def build_connection_string(
    *,
    db_api: str = ASYNC_DB_API,
    user: str = POSTGRES_USER,
    password: str = POSTGRES_PASSWORD,
    host: str = POSTGRES_HOST,
    port: str = POSTGRES_PORT,
    db: str = POSTGRES_DB,
    app_name: str | None = None,
    use_iam_auth: bool = USE_IAM_AUTH,
    region: str = "us-west-2",  # noqa: ARG001
) -> str:
    if use_iam_auth:
        base_conn_str = f"postgresql+{db_api}://{user}@{host}:{port}/{db}"
    else:
        base_conn_str = f"postgresql+{db_api}://{user}:{password}@{host}:{port}/{db}"

    if app_name and db_api != "asyncpg":
        if "?" in base_conn_str:
            return f"{base_conn_str}&application_name={app_name}"
        else:
            return f"{base_conn_str}?application_name={app_name}"
    return base_conn_str


if LOG_POSTGRES_LATENCY:

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(  # type: ignore
        conn,
        cursor,  # noqa: ARG001
        statement,  # noqa: ARG001
        parameters,  # noqa: ARG001
        context,  # noqa: ARG001
        executemany,  # noqa: ARG001
    ):
        conn.info["query_start_time"] = time.time()

    @event.listens_for(Engine, "after_cursor_execute")
    def after_cursor_execute(  # type: ignore
        conn,
        cursor,  # noqa: ARG001
        statement,
        parameters,  # noqa: ARG001
        context,  # noqa: ARG001
        executemany,  # noqa: ARG001
    ):
        total_time = time.time() - conn.info["query_start_time"]
        if total_time > 0.1:
            logger.debug(
                f"Query Complete: {statement}\n\nTotal Time: {total_time:.4f} seconds"
            )


if LOG_POSTGRES_CONN_COUNTS:
    checkout_count = 0
    checkin_count = 0

    @event.listens_for(Engine, "checkout")
    def log_checkout(dbapi_connection, connection_record, connection_proxy):  # type: ignore  # noqa: ARG001
        global checkout_count
        checkout_count += 1

        active_connections = connection_proxy._pool.checkedout()
        idle_connections = connection_proxy._pool.checkedin()
        pool_size = connection_proxy._pool.size()
        logger.debug(
            "Connection Checkout\n"
            f"Active Connections: {active_connections};\n"
            f"Idle: {idle_connections};\n"
            f"Pool Size: {pool_size};\n"
            f"Total connection checkouts: {checkout_count}"
        )

    @event.listens_for(Engine, "checkin")
    def log_checkin(dbapi_connection, connection_record):  # type: ignore  # noqa: ARG001
        global checkin_count
        checkin_count += 1
        logger.debug(f"Total connection checkins: {checkin_count}")


class SqlEngine:
    """Registry of SQLAlchemy engines keyed by Postgres host index.

    Host index 0 is always the "catalog" host (where the public schema
    lives).  Additional hosts can be registered for tenant routing.
    """

    _engines: dict[int, Engine] = {}
    _readonly_engines: dict[int, Engine] = {}
    _lock: threading.Lock = threading.Lock()
    _readonly_lock: threading.Lock = threading.Lock()
    _app_name: str = POSTGRES_UNKNOWN_APP_NAME

    # ── write engines ──────────────────────────────────────────────

    @classmethod
    def init_engine(
        cls,
        pool_size: int,
        max_overflow: int,
        host_index: int = 0,
        host: str | None = None,
        app_name: str | None = None,  # noqa: ARG003
        db_api: str = SYNC_DB_API,
        use_iam: bool = USE_IAM_AUTH,
        connection_string: str | None = None,
        **extra_engine_kwargs: Any,
    ) -> None:
        with cls._lock:
            if host_index in cls._engines:
                return

            if not connection_string:
                connection_string = build_connection_string(
                    db_api=db_api,
                    host=host or POSTGRES_HOST,
                    app_name=cls._app_name + "_sync",
                    use_iam_auth=use_iam,
                )

            final_engine_kwargs: dict[str, Any] = {}

            if POSTGRES_USE_NULL_POOL:
                final_engine_kwargs.update(extra_engine_kwargs)
                final_engine_kwargs["poolclass"] = pool.NullPool
                final_engine_kwargs.pop("pool_size", None)
                final_engine_kwargs.pop("max_overflow", None)
            else:
                final_engine_kwargs["pool_size"] = pool_size
                final_engine_kwargs["max_overflow"] = max_overflow
                final_engine_kwargs["pool_pre_ping"] = POSTGRES_POOL_PRE_PING
                final_engine_kwargs["pool_recycle"] = POSTGRES_POOL_RECYCLE
                final_engine_kwargs.update(extra_engine_kwargs)

            logger.info(
                f"Creating engine for host_index={host_index} "
                f"with kwargs: {final_engine_kwargs}"
            )
            engine = create_engine(connection_string, **final_engine_kwargs)

            if use_iam:
                event.listen(engine, "do_connect", provide_iam_token)

            cls._engines[host_index] = engine

    @classmethod
    def init_all_engines(
        cls,
        pool_size: int,
        max_overflow: int,
        **extra_engine_kwargs: Any,
    ) -> None:
        """Initialize one engine per configured Postgres host.

        Pool sizes are divided evenly across hosts so total connection
        consumption stays roughly the same.
        """
        num_hosts = len(POSTGRES_HOSTS)
        per_host_pool = max(1, pool_size // num_hosts)
        per_host_overflow = max(0, max_overflow // num_hosts)
        for idx, host in enumerate(POSTGRES_HOSTS):
            cls.init_engine(
                pool_size=per_host_pool,
                max_overflow=per_host_overflow,
                host_index=idx,
                host=host,
                **extra_engine_kwargs,
            )

    # ── readonly engines ───────────────────────────────────────────

    @classmethod
    def init_readonly_engine(
        cls,
        pool_size: int,
        max_overflow: int,
        host_index: int = 0,
        host: str | None = None,
        **extra_engine_kwargs: Any,
    ) -> None:
        with cls._readonly_lock:
            if host_index in cls._readonly_engines:
                return

            if not DB_READONLY_USER or not DB_READONLY_PASSWORD:
                raise ValueError(
                    "Custom database user credentials not configured in environment variables"
                )

            connection_string = build_connection_string(
                user=DB_READONLY_USER,
                password=DB_READONLY_PASSWORD,
                host=host or POSTGRES_HOST,
                use_iam_auth=False,
                db_api=SYNC_DB_API,
            )

            final_engine_kwargs: dict[str, Any] = {}

            if POSTGRES_USE_NULL_POOL:
                final_engine_kwargs.update(extra_engine_kwargs)
                final_engine_kwargs["poolclass"] = pool.NullPool
                final_engine_kwargs.pop("pool_size", None)
                final_engine_kwargs.pop("max_overflow", None)
            else:
                final_engine_kwargs["pool_size"] = pool_size
                final_engine_kwargs["max_overflow"] = max_overflow
                final_engine_kwargs["pool_pre_ping"] = POSTGRES_POOL_PRE_PING
                final_engine_kwargs["pool_recycle"] = POSTGRES_POOL_RECYCLE
                final_engine_kwargs.update(extra_engine_kwargs)

            logger.info(
                f"Creating readonly engine for host_index={host_index} "
                f"with kwargs: {final_engine_kwargs}"
            )
            engine = create_engine(connection_string, **final_engine_kwargs)

            if USE_IAM_AUTH:
                event.listen(engine, "do_connect", provide_iam_token)

            cls._readonly_engines[host_index] = engine

    @classmethod
    def init_all_readonly_engines(
        cls,
        pool_size: int,
        max_overflow: int,
        **extra_engine_kwargs: Any,
    ) -> None:
        num_hosts = len(POSTGRES_HOSTS)
        per_host_pool = max(1, pool_size // num_hosts)
        per_host_overflow = max(0, max_overflow // num_hosts)
        for idx, host in enumerate(POSTGRES_HOSTS):
            cls.init_readonly_engine(
                pool_size=per_host_pool,
                max_overflow=per_host_overflow,
                host_index=idx,
                host=host,
                **extra_engine_kwargs,
            )

    # ── getters ────────────────────────────────────────────────────

    @classmethod
    def get_engine(cls, host_index: int = 0) -> Engine:
        engine = cls._engines.get(host_index)
        if engine is None:
            raise RuntimeError(
                f"Engine for host_index={host_index} not initialized. "
                "Must call init_engine / init_all_engines first."
            )
        return engine

    @classmethod
    def get_readonly_engine(cls, host_index: int = 0) -> Engine:
        engine = cls._readonly_engines.get(host_index)
        if engine is None:
            raise RuntimeError(
                f"Readonly engine for host_index={host_index} not initialized. "
                "Must call init_readonly_engine / init_all_readonly_engines first."
            )
        return engine

    @classmethod
    def get_all_engines(cls) -> dict[int, Engine]:
        return dict(cls._engines)

    # ── metadata ───────────────────────────────────────────────────

    @classmethod
    def set_app_name(cls, app_name: str) -> None:
        cls._app_name = app_name

    @classmethod
    def get_app_name(cls) -> str:
        if not cls._app_name:
            return ""
        return cls._app_name

    # ── lifecycle ──────────────────────────────────────────────────

    @classmethod
    def reset_engine(cls) -> None:
        with cls._lock:
            for engine in cls._engines.values():
                engine.dispose()
            cls._engines.clear()

    @classmethod
    @contextmanager
    def scoped_engine(cls, **init_kwargs: Any) -> Generator[None, None, None]:
        """Context manager that initializes the engine and guarantees cleanup."""
        cls.init_engine(**init_kwargs)
        try:
            yield
        finally:
            cls.reset_engine()


# ── convenience accessors ──────────────────────────────────────────


def get_sqlalchemy_engine(host_index: int = 0) -> Engine:
    return SqlEngine.get_engine(host_index)


def get_readonly_sqlalchemy_engine(host_index: int = 0) -> Engine:
    return SqlEngine.get_readonly_engine(host_index)


# ── session factories ──────────────────────────────────────────────


def _get_host_index_for_tenant(tenant_id: str) -> int:
    """Thin wrapper to keep the import lazy and avoid circular deps."""
    from onyx.db.engine.tenant_host_mapping import get_host_index_for_tenant

    return get_host_index_for_tenant(tenant_id)


@contextmanager
def get_session_with_current_tenant() -> Generator[Session, None, None]:
    """Standard way to get a DB session."""
    tenant_id = get_current_tenant_id()
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        yield session


@contextmanager
def get_session_with_current_tenant_if_none(
    session: Session | None,
) -> Generator[Session, None, None]:
    if session is None:
        tenant_id = get_current_tenant_id()
        with get_session_with_tenant(tenant_id=tenant_id) as session:
            yield session
    else:
        yield session


@contextmanager
def get_session_with_shared_schema() -> Generator[Session, None, None]:
    """Always targets host 0 — the catalog host where public-schema tables live."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    engine = SqlEngine.get_engine(host_index=0)
    with Session(bind=engine, expire_on_commit=False) as session:
        yield session
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@contextmanager
def get_session_with_tenant(*, tenant_id: str) -> Generator[Session, None, None]:
    """Generate a database session for a specific tenant."""
    if not is_valid_schema_name(tenant_id):
        raise HTTPException(status_code=400, detail="Invalid tenant ID")

    host_index = _get_host_index_for_tenant(tenant_id)
    engine = SqlEngine.get_engine(host_index)

    if not MULTI_TENANT and tenant_id == POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE:
        with Session(bind=engine, expire_on_commit=False) as session:
            yield session
        return

    schema_translate_map = {None: tenant_id}
    with engine.connect().execution_options(
        schema_translate_map=schema_translate_map
    ) as connection:
        with Session(bind=connection, expire_on_commit=False) as session:
            yield session


def get_session() -> Generator[Session, None, None]:
    """For use w/ Depends for FastAPI endpoints.

    Has some additional validation, and likely should be merged
    with get_session_with_current_tenant in the future."""
    tenant_id = get_current_tenant_id()
    if tenant_id == POSTGRES_DEFAULT_SCHEMA and MULTI_TENANT:
        raise BasicAuthenticationError(detail="User must authenticate")

    if not is_valid_schema_name(tenant_id):
        raise HTTPException(status_code=400, detail="Invalid tenant ID")

    with get_session_with_current_tenant() as db_session:
        yield db_session


@contextmanager
def get_db_readonly_user_session_with_current_tenant() -> (
    Generator[Session, None, None]
):
    """Generate a database session using a readonly database user for the current tenant."""
    tenant_id = get_current_tenant_id()

    host_index = _get_host_index_for_tenant(tenant_id)
    readonly_engine = get_readonly_sqlalchemy_engine(host_index)

    if not is_valid_schema_name(tenant_id):
        raise HTTPException(status_code=400, detail="Invalid tenant ID")

    if not MULTI_TENANT and tenant_id == POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE:
        with Session(readonly_engine, expire_on_commit=False) as session:
            yield session
        return

    schema_translate_map = {None: tenant_id}
    with readonly_engine.connect().execution_options(
        schema_translate_map=schema_translate_map
    ) as connection:
        with Session(bind=connection, expire_on_commit=False) as session:
            yield session
