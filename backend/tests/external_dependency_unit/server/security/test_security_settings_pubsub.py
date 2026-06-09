"""Cross-process invalidation tests for runtime security settings.

These exercise the Redis pub/sub path that propagates an admin save to every
api_server process. A single test process can't span processes, so we stand up a
second listener thread against the *same* Redis and assert it both receives the
published tenant id and drops the locally-cached entry — exactly what a sibling
process would do on receipt.
"""

import threading
from collections.abc import Generator

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheBackendType
from onyx.configs.constants import OnyxRedisChannels
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import SecuritySettings as SecuritySettingsRow
from onyx.redis.redis_pool import get_raw_redis_client
from onyx.server.security import store as security_store
from onyx.server.security.models import SecuritySettingsOverrides
from onyx.server.security.store import apply_patch
from onyx.server.security.store import get_security_settings
from onyx.server.security.store import invalidate_security_cache
from tests.external_dependency_unit.constants import TEST_TENANT_ID


def _delete_security_settings_row() -> None:
    with get_session_with_current_tenant() as session:
        session.execute(delete(SecuritySettingsRow))
        session.commit()


@pytest.fixture(autouse=True)
def _clean_db_and_cache(
    db_session: Session,  # noqa: ARG001 — requested for side-effect (SQL engine init)
    tenant_context: None,  # noqa: ARG001 — requested for side-effect (tenant contextvar)
) -> Generator[None, None, None]:
    _delete_security_settings_row()
    invalidate_security_cache(TEST_TENANT_ID)
    yield
    _delete_security_settings_row()
    invalidate_security_cache(TEST_TENANT_ID)


def test_apply_patch_publishes_invalidation_to_subscriber() -> None:
    """An admin save must publish the tenant id on the shared channel so other
    processes drop their cached copy. We mirror the production listener loop in a
    second thread and assert it receives the message and pops the cache entry.
    """
    received: list[str] = []
    subscribed = threading.Event()
    got_message = threading.Event()
    stop = threading.Event()

    def _listener() -> None:
        # Drive a raw pubsub directly (rather than store.subscribe()) so the test
        # can wait for the subscribe confirmation before publishing — pub/sub has
        # no persistence, so a message sent before we subscribe would be lost.
        pubsub = get_raw_redis_client().pubsub()
        pubsub.subscribe(OnyxRedisChannels.SECURITY_SETTINGS_INVALIDATE)
        try:
            while not stop.is_set():
                message = pubsub.get_message(timeout=0.5)
                if message is None:
                    continue
                if message["type"] == "subscribe":
                    subscribed.set()
                    continue
                if message["type"] != "message":
                    continue
                tenant_id = message["data"].decode()
                received.append(tenant_id)
                # Mirror what the production listener does on receipt.
                invalidate_security_cache(tenant_id)
                got_message.set()
        finally:
            pubsub.close()

    listener = threading.Thread(target=_listener, daemon=True)
    listener.start()
    try:
        assert subscribed.wait(timeout=2.0), "listener never subscribed"

        # Warm the local cache so there is an entry to observe being dropped.
        get_security_settings()
        assert TEST_TENANT_ID in security_store._CACHE

        apply_patch(
            SecuritySettingsOverrides(user_directory_admin_only=True),
            present_keys={"user_directory_admin_only"},
        )

        assert got_message.wait(timeout=2.0), "listener never received the message"
        assert received == [TEST_TENANT_ID]
        # The in-process fast path also pops this entry, but the subscriber's
        # invalidate keeps it gone — i.e. a sibling process would converge too.
        assert TEST_TENANT_ID not in security_store._CACHE
    finally:
        stop.set()
        listener.join(timeout=2.0)


def test_postgres_backend_skips_pubsub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Onyx Lite runs CACHE_BACKEND=postgres and is single-process, so pub/sub is
    skipped entirely: no listener is started and the publish hook is a no-op."""
    monkeypatch.setattr(security_store, "CACHE_BACKEND", CacheBackendType.POSTGRES)

    assert security_store._pubsub_supported() is False

    # The listener must not start under a non-Redis backend.
    monkeypatch.setattr(security_store, "_LISTENER_STARTED", False)
    security_store._ensure_listener_started()
    assert security_store._LISTENER_STARTED is False

    # The publish hook short-circuits before touching any cache backend, so it
    # must complete without raising even though Postgres has no pub/sub.
    security_store._publish_invalidation(TEST_TENANT_ID)
