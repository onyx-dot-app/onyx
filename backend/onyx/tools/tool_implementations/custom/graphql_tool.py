"""The chat tool of one root field of a GraphQL app. The server writes the
document for that one field, so a call cannot reach a second root field."""

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from graphql import (
    GraphQLArgument,
    GraphQLEnumType,
    GraphQLError,
    GraphQLField,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLInterfaceType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
    IntrospectionQuery,
    Undefined,
    assert_valid_schema,
    build_client_schema,
    build_schema,
    get_named_type,
    is_leaf_type,
    parse,
    print_schema,
    validate,
)
from pydantic import JsonValue

from onyx.external_apps.matching.graphql_parsing import operation_invocations
from onyx.integrations.models import CallCredentials
from onyx.tools.models import (
    CustomToolUserFileSnapshot,
    ToolApprovalScope,
    ToolCallException,
)
from onyx.tools.tool_implementations.custom.custom_tool import ApiTool
from onyx.tools.tool_name import custom_tool_name

SELECTION = "selection"
# An input object deeper than this takes any object, so a recursive filter
# type gives a finite schema.
_MAX_INPUT_DEPTH = 3
_SCALARS: dict[str, dict[str, JsonValue]] = {
    "Int": {"type": "integer"},
    "Float": {"type": "number"},
    "Boolean": {"type": "boolean"},
    "String": {"type": "string"},
    "ID": {"type": "string"},
}


def parse_graphql_schema(sdl: str) -> GraphQLSchema:
    """Raises ``ValueError`` for text that is not a valid schema, such as one
    with no query root type."""
    try:
        schema = build_schema(sdl)
        assert_valid_schema(schema)
        return schema
    except (GraphQLError, TypeError) as e:
        raise ValueError(f"The GraphQL schema is not valid: {e}") from e


def introspection_to_sdl(result: object) -> str:
    """The SDL of an introspection response body. Raises ``ValueError``."""
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        raise ValueError("The endpoint did not return an introspection result.")
    try:
        return print_schema(build_client_schema(cast(IntrospectionQuery, data)))
    except (GraphQLError, TypeError) as e:
        raise ValueError(f"The introspection result is not valid: {e}") from e


def graphql_root_fields(schema: GraphQLSchema) -> list[tuple[str, GraphQLField]]:
    """``(action key, field)`` of each query and mutation root field. The key
    is ``query.<field>`` or ``mutation.<field>``."""
    return [
        (f"{operation}.{name}", field)
        for operation, root in (
            ("query", schema.query_type),
            ("mutation", schema.mutation_type),
        )
        if root is not None
        for name, field in root.fields.items()
    ]


def _input_schema(type_: object, depth: int) -> dict[str, JsonValue]:
    if isinstance(type_, GraphQLNonNull):
        return _input_schema(type_.of_type, depth)
    if isinstance(type_, GraphQLList):
        return {"type": "array", "items": _input_schema(type_.of_type, depth)}
    if isinstance(type_, GraphQLEnumType):
        return {"type": "string", "enum": list(type_.values)}
    if isinstance(type_, GraphQLInputObjectType):
        if depth >= _MAX_INPUT_DEPTH:
            return {"type": "object"}
        return _object_schema(type_.fields, depth + 1)
    if isinstance(type_, GraphQLScalarType):
        return dict(_SCALARS.get(type_.name, {}))
    return {}


def _is_required(field: GraphQLArgument | GraphQLInputField) -> bool:
    return isinstance(field.type, GraphQLNonNull) and field.default_value is Undefined


def _object_schema(
    fields: Mapping[str, GraphQLArgument] | Mapping[str, GraphQLInputField],
    depth: int,
    extra: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    properties: dict[str, JsonValue] = {}
    for name, field in fields.items():
        schema = _input_schema(field.type, depth)
        if field.description:
            schema["description"] = field.description
        properties[name] = schema
    properties.update(extra or {})
    required: list[JsonValue] = [
        name for name, field in fields.items() if _is_required(field)
    ]
    return {"type": "object", "properties": properties, "required": required}


def default_selection(field: GraphQLField) -> str:
    """The scalar and enum fields of the return type, one level deep."""
    named = get_named_type(field.type)
    if is_leaf_type(named):
        return ""
    if isinstance(named, GraphQLObjectType | GraphQLInterfaceType):
        leaves = [
            name
            for name, sub in named.fields.items()
            if is_leaf_type(get_named_type(sub.type))
            and not any(_is_required(arg) for arg in sub.args.values())
        ]
        if leaves:
            return "{ " + " ".join(leaves) + " }"
    return "{ __typename }"


def graphql_tool_parameters(field: GraphQLField) -> dict[str, JsonValue]:
    """The field's arguments, and ``selection`` when it returns an object and
    has no argument of that name."""
    selection = default_selection(field)
    extra: dict[str, JsonValue] = (
        {
            SELECTION: {
                "type": "string",
                "description": (
                    "The fields to return, as a GraphQL selection set. "
                    f"Default: {selection}"
                ),
            }
        }
        if selection and SELECTION not in field.args
        else {}
    )
    return _object_schema(field.args, 0, extra)


def graphql_request(
    schema: GraphQLSchema,
    operation: str,
    field_name: str,
    field: GraphQLField,
    arguments: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    """The request body that calls one root field with variables. Raises
    ``ValueError`` when the schema refuses the document."""
    variables = {name: arguments[name] for name in field.args if name in arguments}
    raw_selection = None if SELECTION in field.args else arguments.get(SELECTION)
    selection = (
        raw_selection.strip()
        if isinstance(raw_selection, str) and raw_selection.strip()
        else default_selection(field)
    )
    if selection and not selection.startswith("{"):
        selection = "{ " + selection + " }"
    declared = ", ".join(f"${name}: {field.args[name].type}" for name in variables)
    passed = ", ".join(f"{name}: ${name}" for name in variables)
    call = f"{field_name}{f'({passed})' if passed else ''} {selection}".rstrip()
    query = f"{operation}{f'({declared})' if declared else ''} {{ {call} }}"
    try:
        document = parse(query)
    except GraphQLError as e:
        raise ValueError(e.message) from e
    if operation_invocations(query) != [(operation, field_name)]:
        raise ValueError("The selection must be one selection set.")
    errors = validate(schema, document)
    if errors:
        raise ValueError(" ".join(error.message for error in errors))
    return {"query": query, "variables": variables}


def graphql_failed(tool_result: CustomToolUserFileSnapshot | JsonValue) -> bool:
    """A GraphQL server reports a failed field with status 200 and an
    ``errors`` list, in each result of a batch. The result keeps any partial
    ``data``."""
    results = tool_result if isinstance(tool_result, list) else [tool_result]
    return any(
        isinstance(result, dict) and bool(result.get("errors")) for result in results
    )


class GraphQLTool(ApiTool):
    """One root field of a GraphQL app. It sends and reads like a REST
    operation; only the request differs."""

    def __init__(
        self,
        integration_id: int,
        action_key: str,
        schema: GraphQLSchema,
        endpoint_url: str,
        headers: dict[str, str],
        approval: ToolApprovalScope | None,
        credentials: CallCredentials | None = None,
        acting_user_id: UUID | None = None,
    ) -> None:
        operation, field_name = action_key.split(".", 1)
        field = dict(graphql_root_fields(schema))[action_key]
        super().__init__(
            integration_id=integration_id,
            action_key=action_key,
            name=custom_tool_name(integration_id, action_key),
            display_name=field_name,
            description=field.description or f"The GraphQL {operation} {field_name}.",
            parameters=graphql_tool_parameters(field),
            base_url=endpoint_url,
            headers=headers,
            approval=approval,
            credentials=credentials,
            acting_user_id=acting_user_id,
        )
        self._schema = schema
        self._operation = operation
        self._field_name = field_name
        self._field = field

    def _request(self, arguments: dict[str, JsonValue]) -> tuple[str, str, JsonValue]:
        try:
            body = graphql_request(
                self._schema, self._operation, self._field_name, self._field, arguments
            )
        except ValueError as e:
            raise ToolCallException(
                message=f"{self._name}: {e}",
                llm_facing_message=f"The {self._name} call is not valid: {e}",
            ) from e
        return "POST", self._base_url, body

    def _failed(self, tool_result: CustomToolUserFileSnapshot | JsonValue) -> bool:
        return graphql_failed(tool_result)
