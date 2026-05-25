from typing import Annotated
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class RestRoute(BaseModel):
    """Recognises a REST request as an action by HTTP method + path. The
    ``path_regex`` is matched against the request path; a named group may
    capture a resource id for the approval prompt (decision uses only the
    matched action, not the capture)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["rest"] = "rest"
    method: str
    path_regex: str
    resource_type: str | None = None


class GraphQLOp(BaseModel):
    """Recognises a GraphQL request as an action by operation type + the root
    field in the request body (the URL is identical for every operation)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["graphql"] = "graphql"
    operation_type: Literal["query", "mutation", "subscription"]
    field: str
    resource_type: str | None = None


# A request matches an action when any of the action's rules fires. The
# discriminated union serialises cleanly so the same shape can later back
# admin-authored custom-app rules and the proxy's bulk ruleset.
MatchRule = Annotated[RestRoute | GraphQLOp, Field(discriminator="kind")]


class EndpointSpec(BaseModel):
    """One logical action a provider can take, owned by code. Binds a stable
    ``id`` ↔ admin display ↔ recognition rules."""

    model_config = ConfigDict(frozen=True)

    id: str  # stable, namespaced: e.g. "slack.messages.read"
    normalised_name: str
    description: str
    matches: list[MatchRule]
    # Prior ids this action has had, so renames don't break stored admin rows.
    aliases: list[str] = []
