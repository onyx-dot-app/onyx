"""
Tests for the `GET /enterprise-settings/custom-analytics-script` handler.

Regression coverage for the multi-tenant case where a pre-auth / anonymous
page load reaches the endpoint with no tenant context resolved (the contextvar
defaults to the public schema, which has no per-tenant `key_value_store`). The
handler must return `None` in that case rather than 500ing with
`UndefinedTable: relation "public.key_value_store" does not exist`.

These are external dependency unit tests because they need a real database but
also need to control the `MULTI_TENANT` setting via patching.
"""

from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.server.enterprise_settings.api import fetch_custom_analytics_script
from onyx.configs.constants import KV_CUSTOM_ANALYTICS_SCRIPT_KEY
from onyx.key_value_store.factory import get_kv_store
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@pytest.fixture(scope="function")
def clean_analytics_script(
    db_session: Session,  # noqa: ARG001
) -> Generator[None, None, None]:
    """Ensure no analytics script is set before/after the test, in the public
    schema, so single-tenant assertions start from a known state. Depends on
    `db_session` to guarantee the SQL engine is initialized before KV access."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        kv_store = get_kv_store()
        kv_store.delete(KV_CUSTOM_ANALYTICS_SCRIPT_KEY)
    except Exception:
        pass
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    yield

    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        get_kv_store().delete(KV_CUSTOM_ANALYTICS_SCRIPT_KEY)
    except Exception:
        pass
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_returns_none_when_tenant_unresolved__multi_tenant() -> None:
    """Pre-auth request on MT: tenant context resolves to the public schema
    (no per-tenant key_value_store). Must return None, not raise."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        with (
            patch("ee.onyx.server.enterprise_settings.api.MULTI_TENANT", True),
            patch(
                "ee.onyx.server.enterprise_settings.api.POSTGRES_DEFAULT_SCHEMA",
                POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            ),
        ):
            assert fetch_custom_analytics_script() is None
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_returns_none_when_no_script_set__single_tenant(
    clean_analytics_script: None,  # noqa: ARG001
) -> None:
    """Single-tenant with no script configured returns None (not an error)."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        with patch("ee.onyx.server.enterprise_settings.api.MULTI_TENANT", False):
            assert fetch_custom_analytics_script() is None
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_returns_script_when_set__single_tenant(
    clean_analytics_script: None,  # noqa: ARG001
) -> None:
    """Single-tenant with a script configured returns the stored script."""
    script = f"console.log('analytics-{uuid4().hex[:8]}');"
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        get_kv_store().store(KV_CUSTOM_ANALYTICS_SCRIPT_KEY, script)
        with patch("ee.onyx.server.enterprise_settings.api.MULTI_TENANT", False):
            assert fetch_custom_analytics_script() == script
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
