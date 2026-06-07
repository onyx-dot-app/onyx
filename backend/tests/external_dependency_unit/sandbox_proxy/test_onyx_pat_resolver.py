"""External-dependency-unit test for `OnyxPatResolver` against a real DB.

Pins the full claim->resolve contract the unit test mocks: `ensure_sandbox_pat`
mints a PAT and persists it (encrypted) on the sandbox row, the resolver claims
the configured Onyx API host, and reads the token back — through real
`EncryptedString` — as the same value on both auth headers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.auth.constants import API_KEY_HEADER_ALTERNATIVE_NAME
from onyx.auth.constants import API_KEY_HEADER_NAME
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.resolvers import onyx_pat as onyx_pat_mod
from onyx.sandbox_proxy.resolvers.onyx_pat import OnyxPatResolver
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import ensure_sandbox_pat
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import create_test_user

_API_HOST = "api.example.com"


def test_claims_then_resolve_round_trips_minted_pat(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_test_user(db_session, "onyx_pat_resolver")
    sandbox = create_sandbox__no_commit(db_session, user.id)
    raw_token = ensure_sandbox_pat(db_session, sandbox, user)
    db_session.commit()

    ctx = InjectionContext(
        sandbox=ResolvedSandbox(
            sandbox_id=sandbox.id,
            user_id=user.id,
            tenant_id=POSTGRES_DEFAULT_SCHEMA,
            sandbox_name="sandbox-test",
            sandbox_ip="127.0.0.1",
        ),
        matched_actions=None,
    )

    monkeypatch.setattr(onyx_pat_mod, "SANDBOX_API_SERVER_URL", f"https://{_API_HOST}")
    resolver = OnyxPatResolver()
    assert resolver.claims(MagicMock(host=_API_HOST, port=443), ctx) is True
    assert resolver.claims(MagicMock(host="slack.com", port=443), ctx) is False

    headers = resolver.resolve(MagicMock(host=_API_HOST, port=443), ctx)

    assert headers[API_KEY_HEADER_NAME] == f"Bearer {raw_token}"
    assert headers[API_KEY_HEADER_ALTERNATIVE_NAME] == f"Bearer {raw_token}"
