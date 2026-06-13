"""Rule matching as a Strategy: each ``MatchRule`` kind has a matcher object
that knows how to test that kind against a request, looked up through a
registry. Adding a new rule kind is "write a ``RuleMatcher`` + register it" —
the dispatch in ``rule_matches`` never changes (open/closed).
"""

from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import ClassVar
from typing import Generic
from typing import get_args
from typing import TypeVar

from onyx.external_apps.matching.request import MatchContext
from onyx.external_apps.providers.actions import GraphQLOp
from onyx.external_apps.providers.actions import MatchRule
from onyx.external_apps.providers.actions import path_matches
from onyx.external_apps.providers.actions import RestRoute

RuleT = TypeVar("RuleT")


class RuleMatcher(ABC, Generic[RuleT]):
    """Strategy: decides whether one kind of ``MatchRule`` fires for a request.

    ``rule_type`` binds the concrete rule class this matcher handles; the
    registry keys on it.
    """

    rule_type: ClassVar[type]

    @abstractmethod
    def matches(self, rule: RuleT, context: MatchContext) -> bool: ...


class RestRouteMatcher(RuleMatcher[RestRoute]):
    rule_type = RestRoute

    def matches(self, rule: RestRoute, context: MatchContext) -> bool:
        if rule.method.upper() != context.request.method.upper():
            return False
        return path_matches(rule.path, context.request.path)


class GraphQLOpMatcher(RuleMatcher[GraphQLOp]):
    rule_type = GraphQLOp

    def matches(self, rule: GraphQLOp, context: MatchContext) -> bool:
        return any(
            operation_type == rule.operation_type and field == rule.field
            for operation_type, field in context.graphql_invocations
        )


# Registry: rule kind -> the (stateless) strategy that evaluates it.
_MATCHERS: dict[type, RuleMatcher[Any]] = {
    RestRoute: RestRouteMatcher(),
    GraphQLOp: GraphQLOpMatcher(),
}


def rule_matches(rule: MatchRule, context: MatchContext) -> bool:
    """Whether ``rule`` fires for ``context``, via the matcher registered for
    its kind."""
    try:
        matcher = _MATCHERS[type(rule)]
    except KeyError:
        raise RuntimeError(
            f"No RuleMatcher registered for rule kind {type(rule).__name__}; "
            "add one in onyx.external_apps.matching.rules."
        )
    return matcher.matches(rule, context)


def _assert_registry_complete() -> None:
    """Guard at import time that every ``MatchRule`` union member has a matcher,
    so a new rule kind can't ship without one."""
    # MatchRule = Annotated[RestRoute | GraphQLOp, Field(...)]: the first arg is
    # the union, whose args are the concrete rule classes.
    annotated_args = get_args(MatchRule)
    union_members = get_args(annotated_args[0]) if annotated_args else ()
    missing = [member for member in union_members if member not in _MATCHERS]
    if missing:
        names = ", ".join(member.__name__ for member in missing)
        raise RuntimeError(f"MatchRule kinds without a registered matcher: {names}")


_assert_registry_complete()
