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
    """Resolve the policy verdict for ``request`` against ``app``'s catalog.

    Returns ``ALWAYS | ASK | DENY`` when one or more catalog actions match (the
    most restrictive of the matched actions' resolved policies), or ``None`` when
    nothing matches — an off-catalog request the caller's business logic governs.
    """
    context = MatchContext(request)
    catalog = get_endpoint_catalog(app.app_type)
    matched_ids = [
        endpoint.id
        for endpoint in catalog
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    ]
    if not matched_ids:
        return None

    stored = get_policies(db_session, app.id)
    # A matched catalog action with no stored row — an app connected before dense
    # seeding, or a catalog action added since its last save — defaults to ASK
    # rather than raising.
    policies = [stored.get(action_id, EndpointPolicy.ASK) for action_id in matched_ids]
    return _most_restrictive(policies)


def _most_restrictive(policies: list[EndpointPolicy]) -> EndpointPolicy:
    return max(policies, key=_SEVERITY.__getitem__)
