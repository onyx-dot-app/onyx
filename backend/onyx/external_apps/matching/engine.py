"""Composes recognition + policy resolution into a single verdict for an
outbound request."""

from dataclasses import dataclass
from dataclasses import field
from typing import Any

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
# Higher integer means stricter, so `max(...)` is the right reducer.
_POLICY_SEVERITY: dict[EndpointPolicy, int] = {
    EndpointPolicy.ALWAYS: 0,
    EndpointPolicy.ASK: 1,
    EndpointPolicy.DENY: 2,
}


@dataclass(frozen=True)
class ActionMatch:
    """The canonical "this request matched a catalog action" record.

    Returned by ``match_action`` (with ``payload`` empty) and finalized by
    ``ExternalAppActionMatcher`` (which decodes the request body and fills
    ``payload`` via ``dataclasses.replace``). Consumed by ``GateAddon`` to
    decide approval flow + credential injection.

    ``action_type`` is the per-endpoint catalog id (e.g.
    ``"slack.messages.write"``), not the owning app's all-caps type — the
    frontend's label map keys off this. ``external_app_id`` is the gate's
    seam to the connected app row for credential lookup.
    """

    action_type: str
    policy: EndpointPolicy
    external_app_id: int
    payload: dict[str, Any] = field(default_factory=dict)


def match_action(
    db_session: Session,
    app: ExternalApp,
    request: ProxiedRequest,
) -> ActionMatch | None:
    """Resolve the matched catalog action and its policy verdict for ``request``.

    Stored rows are the source of truth: only catalog actions with a row for this
    app are gated (the catalog supplies recognition rules; an action with no row
    is un-gated, not defaulted to ASK). Returns the most restrictive matched
    action, or ``None`` when nothing matches.

    ``payload`` is left empty here — body decoding is the caller's
    responsibility (it owns the raw content + content-type). The caller
    finalizes via ``dataclasses.replace(match, payload=decoded)``.
    """
    context = MatchContext(request)
    stored = get_policies(db_session, app.id)
    catalog = get_endpoint_catalog(app.app_type)
    matched = [
        ActionMatch(
            action_type=endpoint.id,
            policy=stored[endpoint.id],
            external_app_id=app.id,
        )
        for endpoint in catalog
        if endpoint.id in stored
        and any(rule_matches(rule, context) for rule in endpoint.matches)
    ]
    if not matched:
        return None
    # Tie-break: most restrictive policy wins. `_POLICY_SEVERITY` is
    # kept local to this module — callers don't need it.
    return max(matched, key=lambda m: _POLICY_SEVERITY[m.policy])
