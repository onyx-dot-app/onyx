from enum import Enum
from typing import Annotated
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import InstanceOf

from onyx.db.enums import EndpointPolicy


class ExternalAppAction(str, Enum):
    """Marker base for every built-in provider's action-id enum.

    Deliberately member-less so each provider can subclass it with its own
    catalog ids (Python forbids subclassing an Enum that already has members).
    Being ``str``-based, members compare equal to and hash like their stored id
    string, so they drop into the ``dict[str, ...]`` policy maps and DB
    string columns transparently while staying a strongly-typed handle that
    other code (e.g. SKILL.md composition) can import and reference by name."""


class RestRoute(BaseModel):
    """Recognises a REST request as an action by HTTP method + path.

    ``path`` is a template compared segment-by-segment against the request path
    (see ``path_matches``): a ``{name}`` segment matches exactly one path
    segment (a resource id), a trailing ``{name...}`` segment matches one or
    more remaining segments (for slash-bearing tails like a file path or a
    ``heads/feature/x`` ref), literal segments must match verbatim, and a single
    trailing slash is ignored. Placeholders name the resource for readability;
    the decision uses only the matched action, not the captured value."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["rest"] = "rest"
    method: str
    path: str
    resource_type: str | None = None

    @field_validator("path")
    @classmethod
    def _wildcard_must_be_trailing(cls, path: str) -> str:
        # `path_matches` only honours a `{name...}` wildcard in the last segment;
        # reject it elsewhere at catalog-load time instead of mis-matching silently.
        if any(seg.endswith("...}") for seg in path.rstrip("/").split("/")[:-1]):
            raise ValueError(
                f"'{{name...}}' wildcard must be the last segment: {path!r}"
            )
        return path


def _segment_matches(expected: str, actual: str) -> bool:
    """One template segment vs one path segment: a ``{name}`` placeholder
    matches any single non-empty segment, a literal must match exactly."""
    if expected.startswith("{") and expected.endswith("}"):
        return bool(actual)  # a placeholder requires a non-empty segment
    return expected == actual


def path_matches(template: str, path: str) -> bool:
    """Whether request ``path`` matches a ``RestRoute.path`` template.

    Segments (split on ``/``) are compared positionally: a ``{name}`` segment
    matches any single non-empty segment, a literal segment must match exactly.
    A trailing ``{name...}`` segment matches one *or more* remaining segments,
    for tails that are themselves slash-bearing (a ``contents`` file path, a
    ``heads/feature/x`` ref). A single trailing slash on either side is ignored.
    """
    expected_segments = template.rstrip("/").split("/")
    actual_segments = path.rstrip("/").split("/")

    last = expected_segments[-1]
    if last.startswith("{") and last.endswith("...}"):
        prefix = expected_segments[:-1]
        tail: list[str] = actual_segments[len(prefix) :]
        # Wildcard must swallow >=1 segment and reject empties (`//`), like `{name}`.
        if not tail or not all(tail):
            return False
        return all(_segment_matches(e, a) for e, a in zip(prefix, actual_segments))

    if len(expected_segments) != len(actual_segments):
        return False
    return all(
        _segment_matches(e, a) for e, a in zip(expected_segments, actual_segments)
    )


class GraphQLOp(BaseModel):
    """Recognises a GraphQL request as an action by operation type + the root
    field in the request body (the URL is identical for every operation)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["graphql"] = "graphql"
    operation_type: Literal["query", "mutation", "subscription"]
    field: str
    resource_type: str | None = None


# A request matches an action when any of the action's rules fires.
MatchRule = Annotated[RestRoute | GraphQLOp, Field(discriminator="kind")]


class EndpointSpec(BaseModel):
    """One logical action a provider can take, owned by code. Binds a stable
    ``id`` ↔ admin display ↔ recognition rules."""

    model_config = ConfigDict(frozen=True)

    # Stable, namespaced id as a provider-specific enum member (e.g.
    # ``SlackAction.MESSAGES_READ`` → "slack.messages.read"). ``InstanceOf``
    # accepts any ``ExternalAppAction`` subclass member while rejecting bare
    # strings, so catalogs can't drift onto untyped ids.
    id: InstanceOf[ExternalAppAction]
    normalised_name: str
    description: str
    matches: tuple[MatchRule, ...]
    # The policy a freshly-created built-in app starts this action at, unless the
    # admin overrides it.
    default_policy: EndpointPolicy = EndpointPolicy.ASK
