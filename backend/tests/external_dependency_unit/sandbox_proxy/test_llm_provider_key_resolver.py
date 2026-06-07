"""External-dependency-unit test for `LLMProviderKeyResolver` against a real DB.

Pins the claim->resolve contract the unit test mocks: an access-scoped
`llm_provider` row's key, stored encrypted, is read back — through real
`EncryptedString` and the build-mode access scoping — onto the provider's wire
auth header for a request to its canonical host.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.llm import remove_llm_provider
from onyx.db.llm import upsert_llm_provider
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.resolvers.llm_provider_key import LLMProviderKeyResolver
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import create_test_user


def test_claims_then_resolve_round_trips_encrypted_key(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "llm_key_resolver")
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"craft-anthropic-{uuid4().hex[:8]}",
            provider="anthropic",
            api_key="sk-ant-round-trip",
            api_key_changed=True,
        ),
        db_session=db_session,
    )
    db_session.commit()

    ctx = InjectionContext(
        sandbox=ResolvedSandbox(
            sandbox_id=uuid4(),
            user_id=user.id,
            tenant_id=POSTGRES_DEFAULT_SCHEMA,
            sandbox_name="sandbox-test",
            sandbox_ip="127.0.0.1",
        ),
        matched_actions=None,
    )

    try:
        resolver = LLMProviderKeyResolver()
        assert resolver.claims(MagicMock(host="api.anthropic.com"), ctx) is True
        assert resolver.claims(MagicMock(host="slack.com"), ctx) is False

        headers = resolver.resolve(MagicMock(host="api.anthropic.com"), ctx)
        assert headers == {"x-api-key": "sk-ant-round-trip"}
    finally:
        remove_llm_provider(db_session, provider.id)
        db_session.commit()
