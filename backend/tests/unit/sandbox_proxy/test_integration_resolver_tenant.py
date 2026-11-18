"""The proxy resolves a credential in the tenant of the sandbox. A refresh
reads the tenant from the context, which the proxy has no request
middleware to set."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

from onyx.db.enums import IntegrationKind
from onyx.external_apps.matching.engine import GatedTarget
from onyx.integrations.models import CallCredentials
from onyx.sandbox_proxy.resolvers.integration import IntegrationResolver
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

MODULE = "onyx.sandbox_proxy.resolvers.integration"


@contextmanager
def _session(tenant_id: str) -> Iterator[MagicMock]:  # noqa: ARG001
    yield MagicMock()


def test_a_credential_resolves_in_the_tenant_of_the_sandbox() -> None:
    seen: list[str | None] = []

    def resolve(*_args: object) -> CallCredentials:
        seen.append(CURRENT_TENANT_ID_CONTEXTVAR.get())
        return CallCredentials(
            integration_id=3,
            auth_method=None,
            connection_id=None,
            connection_user_id=None,
            headers={"Authorization": "Bearer t"},
        )

    sandbox = ResolvedSandbox(
        sandbox_id=uuid4(),
        user_id=uuid4(),
        tenant_id="tenant_a",
        sandbox_name="sandbox",
        sandbox_ip="10.0.0.1",
    )
    before = CURRENT_TENANT_ID_CONTEXTVAR.get()
    with (
        patch(f"{MODULE}.get_session_with_tenant", _session),
        patch(f"{MODULE}.get_integration_by_id", return_value=MagicMock(id=3)),
        patch(f"{MODULE}._matches_live_endpoint", return_value=True),
        patch(f"{MODULE}.fetch_user_by_id", return_value=MagicMock()),
        patch(f"{MODULE}.resolve_call_credentials", resolve),
        patch(f"{MODULE}.emit_credential_access"),
    ):
        headers = IntegrationResolver()._resolve_for_target(
            GatedTarget(integration_id=3, kind=IntegrationKind.MCP, app_name="crm"),
            sandbox,
            MagicMock(),
        )

    assert headers == {"Authorization": "Bearer t"}
    assert seen == ["tenant_a"]
    assert CURRENT_TENANT_ID_CONTEXTVAR.get() == before
