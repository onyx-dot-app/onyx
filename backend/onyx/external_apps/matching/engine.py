"""Composes recognition + policy resolution into a single verdict for an
outbound request."""

from sqlalchemy.orm import Session

from onyx.db.enums import EndpointPolicy
from onyx.db.external_app import get_policies
from onyx.db.models import ExternalApp
from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.registry import get_endpoint_catalog

# DENY is the most restrictive verdict, ALWAYS the least; when several catalog
# actions match one request (e.g. a batched GraphQL body) the strictest wins.
_SEVERITY: dict[EndpointPolicy, int] = {
    EndpointPolicy.ALWAYS: 0,
    EndpointPolicy.ASK: 1,
    EndpointPolicy.DENY: 2,
}


def match_action(
    db_session: Session,
    app: ExternalApp,
    request: ProxiedRequest,
) -> EndpointPolicy | None:
    """Resolve the policy verdict for ``request`` from ``app``'s stored policies.

    Stored rows are the source of truth: only catalog actions with a row for this
    app are gated (the catalog supplies recognition rules; an action with no row
    is un-gated, not defaulted to ASK). Returns the most restrictive policy of the
    matched actions, or ``None`` when nothing matches.
    """
    context = MatchContext(request)
    stored = get_policies(db_session, app.id)
    catalog = get_endpoint_catalog(app.app_type)
    matched_policies = [
        stored[endpoint.id]
        for endpoint in catalog
        if endpoint.id in stored
        and any(rule_matches(rule, context) for rule in endpoint.matches)
    ]
    if not matched_policies:
        return None
    return _most_restrictive(matched_policies)


def _most_restrictive(policies: list[EndpointPolicy]) -> EndpointPolicy:
    return max(policies, key=_SEVERITY.__getitem__)
