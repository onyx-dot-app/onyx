"""The HubSpot provider's OAuth scopes: read scopes (+ the mandatory `oauth`
scope) are requested as required, while write scopes ride under HubSpot's
`optional_scope` param so read-only/free accounts — which can't grant writer
scopes — can still complete OAuth. See ENG-4260."""

from __future__ import annotations

from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.base import OAuthFlowSpec
from onyx.external_apps.providers.hubspot import HubspotProvider
from onyx.external_apps.providers.registry import PROVIDERS


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
