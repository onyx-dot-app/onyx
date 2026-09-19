"""The normalised request the matcher consumes, plus a per-request context that
lazily derives and caches the views rule matchers need."""

from functools import cached_property

from pydantic import BaseModel

from onyx.external_apps.matching.graphql_parsing import parse_invocations


class ProxiedRequest(BaseModel):
    """The normalised form of an outbound sandbox request, transport-agnostic.

    The proxy builds one of these from whatever the sandbox emitted (the Python
    helper, ``curl``, or raw HTTP); the host is already consumed by the proxy's
    app-match, so only the path/method/body that distinguish *actions within an
    app* are carried here.
    """

    method: str  # HTTP verb; compared case-insensitively
    path: str  # URL path, tested against RestRoute.path
    body: bytes | None = None  # raw body; parsed lazily for GraphQLOp matching


class MatchContext:
    """A request paired with the derived views matchers consult.

    Rule matchers are stateless strategies, so the work of interpreting a
    request (e.g. parsing a GraphQL body) lives here and is memoised: it runs at
    most once per request, and only if some rule actually asks for it. A pure
    REST app never triggers GraphQL parsing.
    """

    def __init__(self, request: ProxiedRequest) -> None:
        self.request = request

    @cached_property
    def graphql_invocations(self) -> list[tuple[str, str]]:
        """``(operation_type, root_field)`` pairs the request's body invokes."""
        return parse_invocations(self.request.body)
