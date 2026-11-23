"""The playground is the free trial on playground.onyx.app. Some features are
restricted there: Enterprise-only ones stay visible but cannot change, and a
few are switched off.

Each feature that can be restricted has a key (PlaygroundRestrictedFeature).
PLAYGROUND_RESTRICTIONS is the one list that decides which are restricted
today. A router declares its feature once, a route can declare its own, and
the feature closest to the route wins. `/settings` reports the restricted
features, so the web app shows the same thing from the same source. Reads
pass, so a restricted page still renders; writes are refused here, so the
restriction holds without the web app.

How to use it
-------------
Restrict a whole feature (every write on the router):

    router = APIRouter(
        prefix="/admin/sso",
        dependencies=[Depends(restrict_in_playground(PlaygroundRestrictedFeature.SSO))],
    )

Allow one action on a restricted router: add a member for that action to
PlaygroundRestrictedFeature, remove it from PLAYGROUND_RESTRICTIONS, and give
the route that member. The route's feature replaces the router's feature for
that route only. With a new member LLM_DEFAULT_MODEL, for example:

    PLAYGROUND_RESTRICTIONS = frozenset(PlaygroundRestrictedFeature) - {
        PlaygroundRestrictedFeature.LLM_DEFAULT_MODEL
    }

    @router.post(
        "/default",
        dependencies=[Depends(restrict_in_playground(PlaygroundRestrictedFeature.LLM_DEFAULT_MODEL))],
    )

Restrict one action on an open router: the same line, with the feature in the
list.

Hide a feature completely (reads refused too, so the page cannot load):

    restrict_in_playground(PlaygroundRestrictedFeature.X, block_reads=True)

A setting rather than a route (a field on Settings): ask the list directly
with `is_restricted_in_playground(PlaygroundRestrictedFeature.X)` where the
value is read and where it is written.

Allow a feature later: remove it from PLAYGROUND_RESTRICTIONS. The API,
`/settings` and the web app follow.
"""

from enum import StrEnum

from fastapi import Request
from fastapi.routing import APIRoute

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from shared_configs.configs import IS_PLAYGROUND

PLAYGROUND_RESTRICTED_MESSAGE = (
    "This is a playground limit. The feature is not available here. "
    "Your own Onyx has it."
)


class PlaygroundRestrictedFeature(StrEnum):
    """A feature the playground can restrict. Whether it is restricted today
    is decided by PLAYGROUND_RESTRICTIONS, not by being listed here."""

    # Enterprise-only: visible, not configurable.
    LLM_PROVIDERS = "llm_providers"
    CONTEXTUAL_RAG = "contextual_rag"
    SSO = "sso"
    SCIM = "scim"
    WHITELABEL = "whitelabel"
    HOOKS = "hooks"
    LOG_EXPORT = "log_export"
    STANDARD_ANSWERS = "standard_answers"
    # Switched off: shown off, cannot be turned on.
    ANONYMOUS_ACCESS = "anonymous_access"
    LLM_GATEWAY = "llm_gateway"
    SERVICE_ACCOUNT_KEYS = "service_account_keys"
    EMBEDDING = "embedding"


# The one list. Remove a feature to allow it on the playground.
PLAYGROUND_RESTRICTIONS: frozenset[PlaygroundRestrictedFeature] = frozenset(
    PlaygroundRestrictedFeature
)

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_restricted_in_playground(feature: PlaygroundRestrictedFeature) -> bool:
    return IS_PLAYGROUND and feature in PLAYGROUND_RESTRICTIONS


def playground_restrictions() -> list[PlaygroundRestrictedFeature]:
    """What `/settings` reports: empty off the playground."""
    if not IS_PLAYGROUND:
        return []
    return sorted(PLAYGROUND_RESTRICTIONS)


class PlaygroundRestriction:
    """FastAPI dependency that refuses a request when its feature is
    restricted.

    Create it with `restrict_in_playground(...)`, see the module docstring for
    the scenarios. Writes are refused; reads pass unless `block_reads` is set.
    When a router and one of its routes both carry a restriction, only the
    route's restriction acts.
    """

    def __init__(
        self, feature: PlaygroundRestrictedFeature, *, block_reads: bool
    ) -> None:
        self.feature = feature
        self.block_reads = block_reads

    # Async on purpose: a sync dependency runs in the threadpool, which costs
    # a thread hop on every request. Async runs inline and costs nothing
    # measurable when the flag is off.
    async def __call__(self, request: Request) -> None:
        if not IS_PLAYGROUND:
            return
        if self._has_route_level_restriction(request):
            return
        if self.feature not in PLAYGROUND_RESTRICTIONS:
            return
        if not self.block_reads and request.method in _READ_METHODS:
            return
        raise OnyxError(
            OnyxErrorCode.PLAYGROUND_RESTRICTED, PLAYGROUND_RESTRICTED_MESSAGE
        )

    def _has_route_level_restriction(self, request: Request) -> bool:
        """True when the matched route carries a restriction closer to it than
        this one. That restriction decides; this one steps aside."""
        route = request.scope.get("route")
        if not isinstance(route, APIRoute):
            return False
        # FastAPI lists router-level dependencies before the route's own, so
        # the last restriction on the route is the one closest to it.
        restrictions = [
            dependency.dependency
            for dependency in route.dependencies
            if isinstance(dependency.dependency, PlaygroundRestriction)
        ]
        return bool(restrictions) and restrictions[-1] is not self


def restrict_in_playground(
    feature: PlaygroundRestrictedFeature, *, block_reads: bool = False
) -> PlaygroundRestriction:
    """Build the dependency for `Depends(...)` on a router or a route."""
    return PlaygroundRestriction(feature, block_reads=block_reads)
