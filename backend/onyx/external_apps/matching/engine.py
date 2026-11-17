"""Recognize app actions independently of saved permission settings."""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from onyx.db.enums import POLICY_SEVERITY, ActionPolicy, IntegrationKind
from onyx.db.models import ExternalApp
from onyx.external_apps.matching.request import MatchContext, ProxiedRequest
from onyx.external_apps.matching.rules import rule_matches
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.utils.logger import setup_logger

logger = setup_logger()

# action_type for a domain-matched request that hit no catalog action.
WHOLE_DOMAIN_ACTION_TYPE = "unspecified"


class MatchedAction(BaseModel):
    """One catalog action a request invoked, with the display strings the
    FE renders. Carried verbatim from matcher through DB JSONB to API."""

    model_config = ConfigDict(frozen=True)

    action_type: str
    display_name: str
    description: str
    policy: ActionPolicy


class GatedTarget(BaseModel):
    """The integration a gated request is attributed to. Lookups key off
    ``integration_id``, never ``app_name``, which is not unique."""

    model_config = ConfigDict(frozen=True)

    integration_id: int
    kind: IntegrationKind
    app_name: str


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

    @field_validator("actions")
    @classmethod
    def _strictest_first(
        cls, actions: tuple[MatchedAction, ...]
    ) -> tuple[MatchedAction, ...]:
        """Sort strictest-policy-first and reject empty, so ``actions[0]`` always
        drives the verdict however a producer built the tuple."""
        if not actions:
            raise ValueError("AllMatchedActions.actions must be non-empty")
        return tuple(
            sorted(actions, key=lambda a: POLICY_SEVERITY[a.policy], reverse=True)
        )

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
                policy = ActionPolicy(action["policy"])
            except (KeyError, TypeError, ValueError):
                continue
            raw_action_type = action.get("action_type")
            if not isinstance(raw_action_type, str):
                continue
            action_type = raw_action_type

        if policy is ActionPolicy.ASK:
            action_types.add(action_type)
    return sorted(action_types)


def resolve_app_for_url(
    url: str,
    apps: Iterable[ExternalApp],
) -> ExternalApp | None:
    """The first app with an ``upstream_url_patterns`` entry that matches
    ``url``. A malformed built-in regex is skipped."""
    for app in apps:
        for regex in app.upstream_url_regexes:
            try:
                if re.fullmatch(regex, url):
                    return app
            except re.error:
                logger.warning(
                    "skipping malformed upstream_url_pattern app_id=%s pattern=%r",
                    app.id,
                    regex,
                )
    return None


def recognize_actions(
    app: ExternalApp,
    request: ProxiedRequest,
) -> tuple[MatchedAction, ...]:
    """Identify actions with catalog defaults, strictest first. The proxy
    resolves saved policies."""
    context = MatchContext(request)
    catalog = get_endpoint_catalog(app.app_type)
    matched = [
        MatchedAction(
            action_type=endpoint.id,
            display_name=endpoint.normalised_name,
            description=endpoint.description,
            policy=endpoint.default_policy,
        )
        for endpoint in catalog
        if any(rule_matches(rule, context) for rule in endpoint.matches)
    ]
    if not matched:
        matched = [
            MatchedAction(
                action_type=WHOLE_DOMAIN_ACTION_TYPE,
                display_name="Perform action",
                description=f"{request.method} {request.path}",
                policy=ActionPolicy.ASK,
            )
        ]
    return tuple(sorted(matched, key=lambda a: POLICY_SEVERITY[a.policy], reverse=True))
