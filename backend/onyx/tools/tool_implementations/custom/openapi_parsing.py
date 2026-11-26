import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, unquote, urlencode

import yaml
from pydantic import BaseModel, JsonValue
from yaml.composer import ComposerError

from onyx.llm.models import ToolDefinition
from onyx.tools.tool_name import sanitize_tool_name
from onyx.utils.unique_key_yaml import UniqueKeySafeLoader

REQUEST_BODY = "requestBody"
# The operation keys of an OpenAPI path item. Its other keys, such as
# `parameters` and `summary`, apply to the whole path.
OPENAPI_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
# The HTTP methods that an API tool sends.
TOOL_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


class _OpenApiYamlLoader(UniqueKeySafeLoader):
    """Keeps timestamps as text: the parsed spec must stay JSON. As in YAML
    1.2, only true and false are booleans: ``on``, ``off``, ``yes`` and ``no``
    stay text. Refuses aliases: a few nested aliases expand to gigabytes, and
    OpenAPI reuses parts with ``$ref``. Refuses duplicate keys, as JSON
    Schema and OpenAPI require unique keys."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            raise ComposerError(
                None,
                None,
                "YAML aliases (*name) are not supported. Use $ref.",
                self.peek_event().start_mark,
            )
        return super().compose_node(parent, index)


def _construct_timestamp(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> str:
    return str(loader.construct_scalar(node))


_OpenApiYamlLoader.add_constructor("tag:yaml.org,2002:timestamp", _construct_timestamp)
_OpenApiYamlLoader.yaml_implicit_resolvers = {
    first: [
        (tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"
    ]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_OpenApiYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def parse_openapi_document(document: str) -> dict[str, Any]:
    """An OpenAPI document stored as JSON or YAML text."""
    try:
        parsed = _load_openapi_document(document)
    except RecursionError as e:
        raise ValueError("The OpenAPI document is nested too deeply.") from e
    if not isinstance(parsed, dict):
        raise ValueError("The OpenAPI document is not an object.")
    return parsed


def _load_openapi_document(document: str) -> Any:
    try:
        return json.loads(document)
    except json.JSONDecodeError:
        pass
    try:
        parsed = yaml.load(document, Loader=_OpenApiYamlLoader)  # noqa: S506
    except yaml.YAMLError as e:
        raise ValueError(f"The OpenAPI document is not JSON or YAML: {e}") from e
    try:
        json.dumps(parsed)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"The OpenAPI document has a value that is not JSON: {e}"
        ) from e
    return parsed


class MethodSpec(BaseModel):
    # Sanitized operationId used in the parsed operation schema.
    name: str
    # Original operationId used for display and stable tool identity.
    raw_name: str
    summary: str
    path: str
    method: str
    spec: dict[str, Any]

    @property
    def display_name(self) -> str:
        """The name an admin sees: the operation summary, or the original
        operationId."""
        return self.spec.get("summary") or self.raw_name

    def get_request_body_schema(self) -> dict[str, Any]:
        content = self.spec.get("requestBody", {}).get("content", {})
        if "application/json" in content:
            return content["application/json"].get("schema")

        if content:
            raise ValueError(
                f"the body is {', '.join(content)}, and only application/json is supported"
            )

        return {}

    def get_query_param_schemas(self) -> list[dict[str, Any]]:
        return [
            param
            for param in self.spec.get("parameters", [])
            if "schema" in param and "in" in param and param["in"] == "query"
        ]

    def get_path_param_schemas(self) -> list[dict[str, Any]]:
        return [
            param
            for param in self.spec.get("parameters", [])
            if "schema" in param and "in" in param and param["in"] == "path"
        ]

    def build_url(
        self,
        base_url: str,
        path_params: Mapping[str, JsonValue],
        query_params: Mapping[str, JsonValue],
    ) -> str:
        encoded_path_params = {
            name: quote(str(value), safe="") for name, value in path_params.items()
        }
        url = f"{base_url}{self.path}"
        try:
            url = url.format(**encoded_path_params)
        except KeyError as e:
            raise ValueError(f"Missing path parameter: {e}") from e
        except IndexError as e:
            raise ValueError(
                f"The path {self.path} has a parameter that is a number or empty."
            ) from e
        if query_params:
            url += f"?{urlencode(query_params)}"
        return url

    def to_tool_definition(self) -> ToolDefinition:
        properties: dict[str, JsonValue] = {}
        if request_body_schema := self.get_request_body_schema():
            properties[REQUEST_BODY] = request_body_schema
        for param in self.get_query_param_schemas() + self.get_path_param_schemas():
            # OpenAPI puts a parameter's description beside its schema; it wins
            # over the schema's own, which often comes from a shared component.
            # A `true` schema admits any value, as `{}` does.
            description = param.get("description")
            schema = {} if param["schema"] is True else param["schema"]
            properties[param["name"]] = (
                {**schema, "description": description}
                if isinstance(schema, dict)
                and isinstance(description, str)
                and description
                else param["schema"]
            )
        return ToolDefinition(
            name=self.name,
            description=self.summary,
            parameters={"type": "object", "properties": properties},
        )

    def validate_spec(self) -> None:
        # Validate url construction
        path_param_schemas = self.get_path_param_schemas()
        dummy_path_dict = {param["name"]: "value" for param in path_param_schemas}
        query_param_schemas = self.get_query_param_schemas()
        dummy_query_dict = {param["name"]: "value" for param in query_param_schemas}
        self.build_url("", dummy_path_dict, dummy_query_dict)

        # Make sure request body doesn't throw an exception
        self.get_request_body_schema()

        # Ensure the method is valid
        if not self.method:
            raise ValueError("HTTP method is not specified.")
        if self.method.upper() not in TOOL_HTTP_METHODS:
            raise ValueError(f"HTTP method '{self.method}' is not supported.")


def resolve_ref(openapi_spec: dict[str, Any], value: Any) -> Any:
    """What the local ``$ref`` (a JSON Pointer in a URI fragment, such as
    ``#/components/...``) of ``value`` points to, else ``value``."""
    ref = value.get("$ref") if isinstance(value, dict) else None
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return value
    target: Any = openapi_spec
    for part in unquote(ref[2:]).split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(target, dict) and key in target:
            target = target[key]
        elif isinstance(target, list) and key.isdigit() and int(key) < len(target):
            target = target[int(key)]
        else:
            return value
    return target


# Shared schemas can reuse each other so much that inlining them grows
# exponentially, as YAML aliases do. This caps the JSON values that the
# inlining of one spec copies.
_MAX_INLINED_NODES = 200_000


class InlineBudget:
    """The values left to copy for the inlining of one spec. One budget
    covers all the operations of the spec."""

    def __init__(self) -> None:
        self.remaining = _MAX_INLINED_NODES


def inline_refs(openapi_spec: dict[str, Any], value: Any, budget: InlineBudget) -> Any:
    """``value`` with each local ``$ref`` in it replaced by a copy of what it
    points to. A reference that is cyclic, not local, or missing becomes
    ``{}``, which admits any value. Once ``budget`` runs out, the rest stays
    as written, with its references."""

    def inline(node: Any, open_refs: frozenset[str]) -> Any:
        if budget.remaining <= 0:
            return node
        budget.remaining -= 1
        if isinstance(node, list):
            return [inline(item, open_refs) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if not isinstance(ref, str):
            return {key: inline(item, open_refs) for key, item in node.items()}
        target = resolve_ref(openapi_spec, node)
        if target is node or ref in open_refs:
            return {}
        resolved = inline(target, open_refs | {ref})
        siblings = {
            key: inline(item, open_refs) for key, item in node.items() if key != "$ref"
        }
        return {**resolved, **siblings} if isinstance(resolved, dict) else resolved

    return inline(value, frozenset())


def operation_parameters(
    openapi_spec: dict[str, Any], path_item: dict[str, Any], operation: dict[str, Any]
) -> list[Any]:
    """The path item's parameters and the operation's, with local references
    resolved. An operation parameter replaces the path parameter with the same
    name and location."""
    merged: dict[tuple[Any, Any], Any] = {}
    for source in (path_item, operation):
        for param in source.get("parameters") or []:
            resolved = resolve_ref(openapi_spec, param)
            key = (
                (resolved.get("name"), resolved.get("in"))
                if isinstance(resolved, dict)
                else (id(resolved), None)
            )
            merged[key] = resolved
    return list(merged.values())


def resolved_operation(
    openapi_spec: dict[str, Any],
    path_item: dict[str, Any],
    operation: dict[str, Any],
    budget: InlineBudget,
) -> dict[str, Any]:
    """``operation`` with the parameters of its path item and with the local
    references in its parameters and request body inlined."""
    resolved = dict(operation)
    if parameters := operation_parameters(openapi_spec, path_item, operation):
        resolved["parameters"] = inline_refs(openapi_spec, parameters, budget)
    if "requestBody" in operation:
        resolved["requestBody"] = inline_refs(
            openapi_spec, operation["requestBody"], budget
        )
    return resolved


def openapi_to_method_spec(
    openapi_spec: dict[str, Any],
    path: str,
    path_item: dict[str, Any],
    method_name: str,
    method: dict[str, Any],
    budget: InlineBudget,
) -> MethodSpec:
    raw_name = method.get("operationId")
    if not raw_name:
        raise ValueError(
            f"Operation ID is not specified for {method_name.upper()} {path}"
        )

    summary = method.get("summary") or method.get("description")
    if not summary:
        raise ValueError(f"Summary is not specified for {method_name.upper()} {path}")

    return MethodSpec(
        name=sanitize_tool_name(raw_name),
        raw_name=raw_name,
        summary=summary,
        path=path,
        method=method_name,
        spec=resolved_operation(openapi_spec, path_item, method, budget),
    )


def openapi_operations(
    openapi_spec: dict[str, Any],
) -> list[tuple[str, dict[str, Any], str, dict[str, Any]]]:
    """Each operation as (path, path item, method, operation)."""
    paths = openapi_spec.get("paths")
    return [
        (path, path_item, method_name, method)
        for path, path_item in (paths.items() if isinstance(paths, dict) else [])
        if isinstance(path_item, dict)
        for method_name, method in path_item.items()
        if str(method_name).lower() in OPENAPI_METHODS and isinstance(method, dict)
    ]


def inline_path_parameters(openapi_spec: dict[str, Any]) -> dict[str, Any]:
    """``openapi_spec`` with each path item cut to its operations, and the
    path item's parameters copied into each operation, with local references
    resolved as ``resolved_operation`` does, and each server URL with its
    variable defaults filled in. Releases before the api_app table read only
    this shape from ``tool.openapi_schema``."""
    paths: dict[str, dict[str, Any]] = {}
    budget = InlineBudget()
    for path, path_item, method_name, method in openapi_operations(openapi_spec):
        paths.setdefault(path, {})[method_name] = resolved_operation(
            openapi_spec, path_item, method, budget
        )
    servers = openapi_spec.get("servers")
    if not isinstance(servers, list):
        return {**openapi_spec, "paths": paths}
    return {
        **openapi_spec,
        "paths": paths,
        "servers": [
            (
                {
                    **server,
                    "url": _with_variable_defaults(
                        server["url"], server.get("variables")
                    ),
                }
                if isinstance(server, dict) and isinstance(server.get("url"), str)
                else server
            )
            for server in servers
        ],
    }


def check_unique_name(method_spec: MethodSpec, seen_names: dict[str, str]) -> None:
    """Raise if another operation has the sanitized name of ``method_spec``;
    else record it in ``seen_names``."""
    prior_raw = seen_names.get(method_spec.name)
    if prior_raw == method_spec.raw_name:
        raise ValueError(
            f"Duplicate operation ID '{method_spec.raw_name}'. Each operation must have a unique operationId."
        )
    if prior_raw is not None:
        raise ValueError(
            f"Operation IDs '{prior_raw}' and '{method_spec.raw_name}' both sanitize to "
            f"'{method_spec.name}'. Rename one so the LLM-facing names stay distinct."
        )
    seen_names[method_spec.name] = method_spec.raw_name


def openapi_to_method_specs(openapi_spec: dict[str, Any]) -> list[MethodSpec]:
    method_specs = []
    seen_names: dict[str, str] = {}
    budget = InlineBudget()
    for path, path_item, method_name, method in openapi_operations(openapi_spec):
        method_spec = openapi_to_method_spec(
            openapi_spec, path, path_item, method_name, method, budget
        )
        check_unique_name(method_spec, seen_names)
        method_specs.append(method_spec)

    return method_specs


def _with_variable_defaults(url: str, variables: object) -> str:
    """``url`` with each ``{name}`` server variable set to its default. A
    variable with no string default stays as it is."""
    if not isinstance(variables, dict):
        return url

    def default(match: re.Match[str]) -> str:
        variable = variables.get(match.group(1))
        value = variable.get("default") if isinstance(variable, dict) else None
        return value if isinstance(value, str) else match.group(0)

    return re.sub(r"\{([^{}]+)\}", default, url)


def openapi_to_url(openapi_schema: dict[str, Any]) -> str:
    """The one server URL of an OpenAPI schema, with its variables set to
    their defaults and no trailing slash: each path starts with one. Raises
    ``ValueError`` unless there is exactly one."""
    urls: list[str] = []

    servers = openapi_schema.get("servers", [])
    for server in servers:
        url = server.get("url")
        if url is not None and not isinstance(url, str):
            raise ValueError("`servers[].url` must be a string")
        if url:
            urls.append(_with_variable_defaults(url, server.get("variables")))

    if len(urls) != 1:
        raise ValueError(
            f"Expected exactly one URL in OpenAPI schema, but found {urls}"
        )

    return urls[0].rstrip("/")


def validate_openapi_schema(
    schema: dict[str, Any], *, check_server_url: bool = True
) -> None:
    """Raise ``ValueError`` if ``schema`` is not an OpenAPI 3 schema that the
    custom tools can call. Without ``check_server_url``, the schema needs no
    server URL."""

    # check basic structure
    if "info" not in schema:
        raise ValueError("`info` section is required in OpenAPI schema")

    info = schema["info"]
    if "title" not in info:
        raise ValueError("`title` is required in `info` section of OpenAPI schema")

    if "openapi" not in schema and "swagger" in schema:
        raise ValueError(
            f"Swagger {schema['swagger']} is not supported. Convert the spec to OpenAPI 3."
        )
    if "openapi" not in schema:
        raise ValueError(
            "`openapi` field which specifies OpenAPI schema version is required"
        )
    openapi_version = schema["openapi"]
    if not openapi_version.startswith("3."):
        raise ValueError(f"OpenAPI version '{openapi_version}' is not supported")

    if "paths" not in schema:
        raise ValueError("`paths` section is required in OpenAPI schema")

    servers = schema.get("servers", [])
    if not isinstance(servers, list) or not all(
        isinstance(server, dict) for server in servers
    ):
        raise ValueError("`servers` must be a list of objects")
    if check_server_url:
        openapi_to_url(schema)

    method_specs = openapi_to_method_specs(schema)
    for method_spec in method_specs:
        method_spec.validate_spec()
