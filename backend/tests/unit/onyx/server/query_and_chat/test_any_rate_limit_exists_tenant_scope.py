"""Regression coverage for tenant scoping of the token-rate-limit existence cache.

`any_rate_limit_exists()` gates all token-rate-limit enforcement, so its per-process
cache must be keyed by tenant. Otherwise the first tenant to warm it fixes the answer
for every tenant on that worker, and a tenant that configured limits gets them silently
bypassed."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock
from unittest.mock import patch

import onyx.server.query_and_chat.token_limit as token_limit
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@contextmanager
def _tenant(tenant_id: str) -> Iterator[None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def _session_for(tenant_id: str | None) -> MagicMock:
    """Fake `get_session_with_current_tenant()` result: tenant_a has an enabled rate
    limit (scalar returns an id), every other tenant has none (scalar returns None)."""
    session = MagicMock()
    session.scalar.return_value = 1 if tenant_id == "tenant_a" else None
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = False
    return ctx


def test_any_rate_limit_exists_is_tenant_scoped_and_cached() -> None:
    token_limit._any_rate_limit_exists_cache.clear()

    def fake_get_session() -> MagicMock:
        return _session_for(CURRENT_TENANT_ID_CONTEXTVAR.get())

    with patch.object(
        token_limit, "get_session_with_current_tenant", side_effect=fake_get_session
    ) as mock_get_session:
        with _tenant("tenant_a"):
            assert token_limit.any_rate_limit_exists() is True
            # second call for the same tenant is served from cache
            assert token_limit.any_rate_limit_exists() is True

        # a different tenant must not inherit tenant_a's cached answer
        with _tenant("tenant_b"):
            assert token_limit.any_rate_limit_exists() is False

    # one DB check per tenant (2), not 3 — tenant_a's second call hit the cache
    assert mock_get_session.call_count == 2


def test_invalidate_clears_only_current_tenant() -> None:
    token_limit._any_rate_limit_exists_cache.clear()

    def fake_get_session() -> MagicMock:
        return _session_for(CURRENT_TENANT_ID_CONTEXTVAR.get())

    with patch.object(
        token_limit, "get_session_with_current_tenant", side_effect=fake_get_session
    ) as mock_get_session:
        with _tenant("tenant_a"):
            assert token_limit.any_rate_limit_exists() is True
        with _tenant("tenant_b"):
            assert token_limit.any_rate_limit_exists() is False
            token_limit.invalidate_any_rate_limit_exists_cache()  # clears tenant_b only
        # tenant_a stays cached; tenant_b was invalidated so it re-checks
        with _tenant("tenant_a"):
            assert token_limit.any_rate_limit_exists() is True
        with _tenant("tenant_b"):
            assert token_limit.any_rate_limit_exists() is False

    # tenant_a checked once, tenant_b checked twice (invalidated) => 3
    assert mock_get_session.call_count == 3
