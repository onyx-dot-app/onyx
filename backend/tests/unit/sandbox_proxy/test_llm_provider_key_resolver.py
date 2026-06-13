"""Unit tests for `LLMProviderKeyResolver`.

Coverage: the canonical-host claim rule, the per-provider header conventions
(pinned against the spec, not the resolver's own table), and the fail-closed
cases the dispatcher maps to a 403. The encrypt/store/read round-trip against a
real DB is pinned in
`tests/external_dependency_unit/sandbox_proxy/test_llm_provider_key_resolver.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.resolvers import llm_provider_key
from onyx.sandbox_proxy.resolvers.llm_provider_key import LLMProviderKeyResolver
from onyx.server.features.build.configs import BUILD_MODE_ALLOWED_PROVIDER_TYPES
from tests.unit.sandbox_proxy.conftest import make_flow
from tests.unit.sandbox_proxy.conftest import make_resolved_sandbox


class _FakeProvider:
    def __init__(self, provider: str, api_key: str | None) -> None:
        self.provider = provider
        self.api_key = api_key


def _noop_db_factory() -> Any:
    @contextmanager
    def factory(tenant_id: str) -> Iterator[Any]:  # noqa: ARG001
        yield MagicMock()

    return factory


@pytest.fixture(autouse=True)
def _patch_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The resolver opens its own tenant session via `get_session_with_tenant`;
    yield a dummy so the patched DB-access functions receive it."""
    monkeypatch.setattr(llm_provider_key, "get_session_with_tenant", _noop_db_factory())


def _ctx() -> InjectionContext:
    return InjectionContext(
        sandbox=make_resolved_sandbox(tenant_id="tenant-7"), matched_actions=None
    )


@pytest.fixture
def resolver() -> LLMProviderKeyResolver:
    return LLMProviderKeyResolver()


def _patch_providers(
    monkeypatch: pytest.MonkeyPatch, providers: list[_FakeProvider]
) -> None:
    monkeypatch.setattr(llm_provider_key, "fetch_user_by_id", lambda *_: object())
    monkeypatch.setattr(
        llm_provider_key,
        "fetch_all_supported_build_llm_providers",
        lambda *_: providers,
    )


def test_claims_only_canonical_hosts(resolver: LLMProviderKeyResolver) -> None:
    for host in ("api.openai.com", "api.anthropic.com", "openrouter.ai"):
        assert resolver.claims(make_flow(host=host).request, _ctx()) is True
        assert resolver.claims(make_flow(host=host.upper()).request, _ctx()) is True
    assert resolver.claims(make_flow(host="api.slack.com").request, _ctx()) is False
    assert resolver.claims(make_flow(host="example.com").request, _ctx()) is False


def test_openai_and_openrouter_render_bearer(
    resolver: LLMProviderKeyResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_providers(
        monkeypatch,
        [_FakeProvider("openai", "sk-oai"), _FakeProvider("openrouter", "sk-or")],
    )
    assert resolver.resolve(make_flow(host="api.openai.com").request, _ctx()) == {
        "Authorization": "Bearer sk-oai"
    }
    assert resolver.resolve(make_flow(host="openrouter.ai").request, _ctx()) == {
        "Authorization": "Bearer sk-or"
    }


def test_anthropic_renders_x_api_key_only(
    resolver: LLMProviderKeyResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_providers(monkeypatch, [_FakeProvider("anthropic", "sk-ant")])
    # x-api-key only — anthropic-version and other SDK headers must survive.
    assert resolver.resolve(make_flow(host="api.anthropic.com").request, _ctx()) == {
        "x-api-key": "sk-ant"
    }


def test_selects_first_provider_of_claimed_type(
    resolver: LLMProviderKeyResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_providers(
        monkeypatch,
        [
            _FakeProvider("openai", "sk-first"),
            _FakeProvider("openai", "sk-second"),
            _FakeProvider("anthropic", "sk-ant"),
        ],
    )
    assert resolver.resolve(make_flow(host="api.openai.com").request, _ctx()) == {
        "Authorization": "Bearer sk-first"
    }


def test_resolve_raises_when_user_missing(
    resolver: LLMProviderKeyResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_provider_key, "fetch_user_by_id", lambda *_: None)
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(make_flow(host="api.openai.com").request, _ctx())


def test_resolve_raises_when_no_provider_of_type(
    resolver: LLMProviderKeyResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_providers(monkeypatch, [_FakeProvider("anthropic", "sk-ant")])
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(make_flow(host="api.openai.com").request, _ctx())


def test_resolve_raises_when_provider_has_no_key(
    resolver: LLMProviderKeyResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_providers(monkeypatch, [_FakeProvider("openai", None)])
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(make_flow(host="api.openai.com").request, _ctx())


# The wire contract per provider, written out independently of the resolver's
# own table so a drifted host/header/prefix is caught, not re-derived from impl.
_EXPECTED_HOST_TABLE = {
    "api.openai.com": ("openai", "Authorization", "Bearer "),
    "api.anthropic.com": ("anthropic", "x-api-key", ""),
    "openrouter.ai": ("openrouter", "Authorization", "Bearer "),
}


def test_host_table_matches_wire_spec() -> None:
    assert llm_provider_key._HOST_TO_PROVIDER == _EXPECTED_HOST_TABLE


def test_host_table_covers_every_build_mode_provider_type() -> None:
    """A new allowed provider type without a host rule would silently leave its
    key in the pod (un-injected), so pin the spec table against the allowed set."""
    covered = {pt for pt, _, _ in _EXPECTED_HOST_TABLE.values()}
    assert covered == set(BUILD_MODE_ALLOWED_PROVIDER_TYPES)
