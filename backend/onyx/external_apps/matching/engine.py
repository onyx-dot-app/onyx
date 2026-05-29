"""Composes recognition + policy resolution into a single verdict for an
outbound request."""

from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from sqlalchemy.orm import Session

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import POLICY_SEVERITY
from onyx.db.external_app import get_policies
from onyx.db.models import ExternalApp
from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.external_apps.providers.registry import get_provider_for_app


class ActionMatch(BaseModel):
    """One catalog action a request invoked, with the display strings the
    FE renders. Carried verbatim from matcher through DB JSONB to API."""

    model_config = ConfigDict(frozen=True)

    action_type: str
    display_name: str
    description: str
    policy: EndpointPolicy


class RequestMatch(BaseModel):
    """Every catalog action the request matched within the resolved app.

    ``actions`` is sorted strictest-policy-first; ``decisive`` returns the
    head, whose policy drives the gate's verdict. A batched GraphQL POST is
    the canonical multi-action case.
    """

    model_config = ConfigDict(frozen=True)

    actions: tuple[ActionMatch, ...]
    app_name: str
    external_app_id: int
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _non_empty(self) -> "RequestMatch":
        if not self.actions:
            raise ValueError("RequestMatch.actions must be non-empty")
        return self

    @property
    def decisive(self) -> ActionMatch:
        """The action whose policy drove the verdict (head of the sorted list)."""
        return self.actions[0]


def match_action(
    db_session: Session,
    app: ExternalApp,
    request: ProxiedRequest,
) -> RequestMatch | None:
    """Resolve every catalog action ``request`` invoked within ``app``.

    Stored policy rows are the source of truth: a catalog action without a
    row is un-gated. ``actions`` is sorted strictest-first so callers can
    treat ``decisive`` as the verdict-driving action. Body decoding is the
    caller's job — ``payload`` is empty here; refill via ``model_copy``.
    """
    context = MatchContext(request)
    stored = get_policies(db_session, app.id)
    catalog = get_endpoint_catalog(app.app_type)
    matched = [
        ActionMatch(
            action_type=endpoint.id,
            display_name=endpoint.normalised_name,
            description=endpoint.description,
            policy=stored[endpoint.id],
        )
        for endpoint in catalog
        if endpoint.id in stored
        and any(rule_matches(rule, context) for rule in endpoint.matches)
    ]
    if not matched:
        return None
    matched.sort(key=lambda a: POLICY_SEVERITY[a.policy], reverse=True)

    provider = get_provider_for_app(app)
    app_name = provider.spec.app_name if provider is not None else app.app_type.value
    return RequestMatch(
        actions=tuple(matched),
        app_name=app_name,
        external_app_id=app.id,
    )
