"""The HubSpot provider's OAuth scopes: read scopes (+ the mandatory `oauth`
scope) are requested as required, while write scopes ride under HubSpot's
`optional_scope` param so read-only/free accounts — which can't grant writer
scopes — can still complete OAuth. See ENG-4260."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest

from onyx.db.enums import ExternalAppType
from onyx.db.models import User
from onyx.external_apps.providers.base import OAuthFlowSpec
from onyx.external_apps.providers.hubspot import HubspotProvider
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.server.features.build.external_apps import oauth as oauth_route


def _provider() -> HubspotProvider:
    provider = PROVIDERS[ExternalAppType.HUBSPOT]
    assert isinstance(provider, HubspotProvider)
    return provider


def test_required_scope_is_read_only_plus_oauth() -> None:
    """The required `scope` carries `oauth` + every read scope and no writes —
    so an account that lacks write access never fails the authorize page."""
    scope = _provider().spec.oauth.scope
    required = set(scope.split())
    assert required == {
        "oauth",
        "crm.objects.owners.read",
        "crm.objects.contacts.read",
        "crm.objects.companies.read",
        "crm.objects.deals.read",
    }
    assert not any(s.endswith(".write") for s in required)


def test_optional_scope_is_exactly_the_writes() -> None:
    """Writer scopes ride under `optional_scope`; HubSpot drops the ones an
    account can't grant rather than failing OAuth for everyone."""
    optional = set(_provider().spec.oauth.optional_scope.split())
    assert optional == {
        "crm.objects.contacts.write",
        "crm.objects.companies.write",
        "crm.objects.deals.write",
    }


def test_optional_scope_defaults_empty() -> None:
    """`optional_scope` is opt-in: a spec that doesn't set it sends nothing."""
    spec = OAuthFlowSpec(
        authorize_url="https://example.com/authorize",
        token_url="https://example.com/token",
        scope="read",
        scope_param="scope",
    )
    assert spec.optional_scope == ""


def test_optional_scope_is_carried_on_the_spec() -> None:
    """When set, the value round-trips onto the (frozen) spec unchanged so the
    authorize-URL builder can emit it under the `optional_scope` param."""
    spec = OAuthFlowSpec(
        authorize_url="https://example.com/authorize",
        token_url="https://example.com/token",
        scope="read",
        scope_param="scope",
        optional_scope="write extra.write",
    )
    assert spec.optional_scope == "write extra.write"


def test_authorize_url_carries_optional_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug this fixes lives in the authorize URL, so exercise the route end
    to end: `start_external_app_oauth` must emit the writes under HubSpot's
    `optional_scope` param and keep them out of required `scope`."""
    oauth = _provider().spec.oauth
    app = SimpleNamespace(
        id=1,
        app_type=ExternalAppType.HUBSPOT,
        skill=SimpleNamespace(name="HubSpot", enabled=True),
        organization_credentials=SimpleNamespace(
            get_value=lambda **_: {
                "client_id": "client-id",
                "client_secret": "client-secret",
            }
        ),
    )
    monkeypatch.setattr(oauth_route, "get_external_app_by_id", lambda *_: app)
    monkeypatch.setattr(oauth_route, "get_current_tenant_id", lambda: "tenant")
    monkeypatch.setattr(oauth_route, "get_redis_client", lambda **_: MagicMock())

    response = oauth_route.start_external_app_oauth(
        external_app_id=app.id,
        user=cast(User, SimpleNamespace(id="user-1")),
        db_session=MagicMock(),
    )

    query = parse_qs(urlparse(response.authorize_url).query)
    assert set(query["optional_scope"][0].split()) == set(oauth.optional_scope.split())
    assert not any(s.endswith(".write") for s in query["scope"][0].split())
