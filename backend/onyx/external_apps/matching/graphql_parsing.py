"""Turns a GraphQL HTTP body into the ``(operation_type, root_field)`` pairs the
matcher reasons about.

Isolated behind one function so the GraphQL library is the only thing this
module knows about — swapping parsers (or hardening the traversal) never touches
the rule-matching layer.
"""

import json

from graphql import (
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLSyntaxError,
    InlineFragmentNode,
    OperationDefinitionNode,
)
from graphql import parse as parse_graphql
from graphql.language import SelectionSetNode


def parse_invocations(body: bytes | None) -> list[tuple[str, str]]:
    """``(operation_type, root_field)`` pairs invoked by a GraphQL request body.

    Handles a single GraphQL POST body or a batched array of them. Returns an
    empty list if the body isn't JSON / isn't a GraphQL request / can't be
    parsed — such a request simply matches no GraphQL rule.
    """
    return [
        invocation
        for query in request_queries(body)
        if query is not None
        for invocation in operation_invocations(query)
    ]


def request_queries(body: bytes | None) -> list[str | None]:
    """The ``query`` of each GraphQL document in a body, single or batched.
    None stands for a document with no string ``query``, or for a body that
    is not JSON."""
    if not body:
        return []
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return [None]
    documents = payload if isinstance(payload, list) else [payload]
    queries: list[str | None] = []
    for document in documents:
        query = document.get("query") if isinstance(document, dict) else None
        queries.append(query if isinstance(query, str) else None)
    return queries


def operation_invocations(query: str) -> list[tuple[str, str]]:
    """``(operation_type, root_field)`` for every root field of every operation
    in a GraphQL document. Fragment spreads and inline fragments at the top
    level are resolved so a field can't be hidden from matching inside a
    fragment. Returns an empty list on a syntax error."""
    try:
        document = parse_graphql(query)
    except GraphQLSyntaxError:
        return []

    fragments = {
        definition.name.value: definition
        for definition in document.definitions
        if isinstance(definition, FragmentDefinitionNode)
    }

    invocations: list[tuple[str, str]] = []
    for definition in document.definitions:
        if not isinstance(definition, OperationDefinitionNode):
            continue
        operation_type = definition.operation.value  # "query" | "mutation" | ...
        invocations.extend(
            (operation_type, field)
            for field in _root_field_names(definition.selection_set, fragments, set())
        )
    return invocations


def _root_field_names(
    selection_set: SelectionSetNode,
    fragments: dict[str, FragmentDefinitionNode],
    seen: set[str],
) -> list[str]:
    """Field names directly under ``selection_set``, expanding inline fragments
    and (cycle-guarded) named fragment spreads at this level."""
    names: list[str] = []
    for selection in selection_set.selections:
        if isinstance(selection, FieldNode):
            names.append(selection.name.value)
        elif isinstance(selection, InlineFragmentNode):
            names.extend(_root_field_names(selection.selection_set, fragments, seen))
        elif isinstance(selection, FragmentSpreadNode):
            name = selection.name.value
            fragment = fragments.get(name)
            if fragment is None or name in seen:
                continue
            names.extend(
                _root_field_names(fragment.selection_set, fragments, seen | {name})
            )
    return names
