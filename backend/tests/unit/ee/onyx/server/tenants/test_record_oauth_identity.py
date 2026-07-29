"""Guards that `record_oauth_identity` only touches the mapping table on cloud.

`public.user_tenant_mapping` is created by the `alembic_tenants` tree, which only
multi-tenant deployments run. Opening a session against it anywhere else would
raise on every OAuth login, so the `MULTI_TENANT` guard is load-bearing rather
than an optimization.
"""

from unittest.mock import MagicMock, patch

from ee.onyx.server.tenants.user_mapping import record_oauth_identity

_MAPPING_MODULE = "ee.onyx.server.tenants.user_mapping"


def _run(*, multi_tenant: bool) -> MagicMock:
    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", multi_tenant),
        patch(f"{_MAPPING_MODULE}.get_session_with_shared_schema") as session_ctx,
    ):
        record_oauth_identity(
            email="user@example.com",
            tenant_id="tenant_abc",
            oauth_name="google",
            account_id="sub-123",
        )
    return session_ctx


def test_single_tenant_opens_no_session() -> None:
    assert _run(multi_tenant=False).call_count == 0


def test_multi_tenant_updates_the_mapping_row() -> None:
    session_ctx = _run(multi_tenant=True)
    assert session_ctx.call_count == 1

    db_session = session_ctx.return_value.__enter__.return_value
    db_session.query.return_value.filter.return_value.update.assert_called_once_with(
        {"oauth_name": "google", "account_id": "sub-123"}
    )
    db_session.commit.assert_called_once()
