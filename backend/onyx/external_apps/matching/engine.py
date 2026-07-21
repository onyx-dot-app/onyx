"""Composes recognition + policy resolution into a single verdict for an
outbound request."""

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from onyx.db.enums import POLICY_SEVERITY, EndpointPolicy, ExternalAppType, GatedAppKind
from onyx.db.gated_app import get_action_policies
from onyx.db.models import ExternalApp
from onyx.external_apps.matching.request import MatchContext, ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.registry import (
    effective_policy,
    get_endpoint_catalog,
    get_provider_for_app,
)

# action_type for a domain-matched request that hit no catalog action.
WHOLE_DOMAIN_ACTION_TYPE = "unspecified"


class MatchedAction(BaseModel):
    """One catalog action a request invoked, with the display strings the
    FE renders. Carried verbatim from matcher through DB JSONB to API."""

    model_config = ConfigDict(frozen=True)

    action_type: str
    display_name: str
    description: str
    policy: EndpointPolicy


class GatedTarget(BaseModel):
    """The connected app/server a gated request is attributed to.

    ``id`` indexes the table named by ``kind`` — ``external_app`` or
    ``mcp_server``. Lookups key off ``(kind, id)``, never ``app_name``: the
    latter isn't unique across instances (self-hosted GitLab/Jira share an
    app_type, and two MCP servers can share a display name).
    """

    model_config = ConfigDict(frozen=True)

    kind: GatedAppKind
    id: int
    app_name: str

    @property
    def key(self) -> tuple[GatedAppKind, int]:
        """The ``(kind, id)`` pair — same shape as ``GatedApp.target_key``, so
        live matches compare directly against persisted grants."""
        return self.kind, self.id


class AllMatchedActions(BaseModel):
    """Every catalog action the request matched within the resolved app.

    ``actions`` is sorted strictest-policy-first; ``governing_action`` returns the
    head, whose policy drives the gate's verdict. A batched GraphQL POST is
    the canonical multi-action case. ``target`` names the connected app/server
    the whole approval pipeline attributes the request to.
    """

    model_config = ConfigDict(frozen=True)

    actions: tuple[MatchedAction, ...]
    target: GatedTarget
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _non_empty(self) -> "AllMatchedActions":
        if not self.actions:
            raise ValueError("AllMatchedActions.actions must be non-empty")
        return self

    @classmethod
    def from_actions(
        cls,
        actions: Iterable[MatchedAction],
        target: GatedTarget,
        payload: dict[str, Any] | None = None,
    ) -> "AllMatchedActions":
        """Construct with the strictest-first sort applied, so every producer
        upholds the ``actions[0]`` verdict invariant."""
        ordered = tuple(
            sorted(actions, key=lambda a: POLICY_SEVERITY[a.policy], reverse=True)
        )
        return cls(actions=ordered, target=target, payload=payload or {})

    @property
    def governing_action(self) -> MatchedAction:
        """The action whose policy drove the verdict (head of the sorted list)."""
        return self.actions[0]

    @property
    def app_name(self) -> str:
        return self.target.app_name


PersistedMatchedAction = Mapping[str, Any]
ActionLike = MatchedAction | PersistedMatchedAction


def actions_requiring_approval(actions: Iterable[ActionLike]) -> list[str]:
    """Return the action types whose policy requires a user approval.

    The live gate works with ``MatchedAction`` models while the approval API
    reads the same shape back from JSONB. Keeping both paths here avoids
    mismatched grant semantics between current and persisted requests.
    """
    action_types: set[str] = set()
    for action in actions:
        if isinstance(action, MatchedAction):
            policy = action.policy
            action_type = action.action_type
        else:
            try:
                policy = EndpointPolicy(action["policy"])
            except (KeyError, TypeError, ValueError):
                continue
            raw_action_type = action.get("action_type")
            if not isinstance(raw_action_type, str):
                continue
            action_type = raw_action_type

        if policy is EndpointPolicy.ASK:
            action_types.add(action_type)
    return sorted(action_types)


def _app_name(app: ExternalApp) -> str:
    provider = get_provider_for_app(app)
    if provider is not None:
        return provider.spec.app_name
    # CUSTOM apps have no provider; use their independently editable display name.
    if app.app_type == ExternalAppType.CUSTOM:
        return app.name
    return app.app_type.value


def recognize_actions(
    db_session: Session,
    app: ExternalApp,
    request: ProxiedRequest,
) -> AllMatchedActions | None:
    """Which catalog action(s) ``request`` invokes within ``app`` — pure
    recognition, no credential knowledge.

    Returns an ``AllMatchedActions`` over every catalog action whose rules fire (each
    carrying its ``effective_policy`` — stored override else catalog default),
    sorted strictest-first so ``actions[0]`` is the verdict, or ``None`` when no
    catalog action matches. The credential gate and the whole-domain fallback are
    the caller's job (see ``apply_credential_gate``). ``payload`` is left empty here; refill
    it via ``model_copy``.
    """
    context = MatchContext(request)
    stored = get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, app.id)
    catalog = get_endpoint_catalog(app.app_type)
    matched = [
        MatchedAction(
            action_type=endpoint.id,
            display_name=endpoint.normalised_name,
            description=endpoint.description,
            policy=effective_policy(endpoint, stored),
        )
        for endpoint in catalog
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    ]
    if not matched:
        return None
    return AllMatchedActions.from_actions(
        matched,
        GatedTarget(kind=GatedAppKind.EXTERNAL_APP, id=app.id, app_name=_app_name(app)),
    )


def apply_credential_gate(
    app: ExternalApp,
    request: ProxiedRequest,
    matched_actions: AllMatchedActions | None,
    *,
    is_available: bool,
) -> AllMatchedActions | None:
    """Apply the credential gate to a pure ``recognize_actions`` result, given
    whether the app ``is_available`` (is active and injectable — the caller resolves
    that). Pure: no DB or credential access.

    - ``is_available`` + a catalog action matched → those actions, unchanged.
    - ``is_available`` + nothing matched → gate the whole domain under a default ``ASK``.
    - not ``is_available`` → keep only a recorded ``DENY`` (an explicit block fires with
      or without a credential), else ``None`` (forward the request bare, no prompt).
    """
    if not is_available:
        if matched_actions is None:
            return None
        deny = tuple(
            a for a in matched_actions.actions if a.policy is EndpointPolicy.DENY
        )
        return matched_actions.model_copy(update={"actions": deny}) if deny else None
    if matched_actions is not None:
        return matched_actions
    return AllMatchedActions(
        actions=(
            MatchedAction(
                action_type=WHOLE_DOMAIN_ACTION_TYPE,
                display_name="Perform action",
                description=f"{request.method} {request.path}",
                policy=EndpointPolicy.ASK,
            ),
        ),
        target=GatedTarget(
            kind=GatedAppKind.EXTERNAL_APP, id=app.id, app_name=_app_name(app)
        ),
    )
