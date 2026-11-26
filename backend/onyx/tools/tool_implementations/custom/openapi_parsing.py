import json
import re
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import quote, urlencode

import yaml
from pydantic import BaseModel, JsonValue

from onyx.llm.models import ToolDefinition
from onyx.tools.tool_name import sanitize_tool_name

REQUEST_BODY = "requestBody"
# The operation keys of an OpenAPI path item. Its other keys, such as
# `parameters` and `summary`, apply to the whole path.
OPENAPI_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class _OpenApiYamlLoader(yaml.SafeLoader):
    """Keeps timestamps as text: the parsed spec must stay JSON. As in YAML
    1.2, only true and false are booleans: ``on``, ``off``, ``yes`` and ``no``
    stay text."""


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
        parsed = json.loads(document)
    except json.JSONDecodeError:
        try:
            parsed = yaml.load(document, Loader=_OpenApiYamlLoader)  # noqa: S506
        except yaml.YAMLError as e:
            raise ValueError(f"The OpenAPI document is not JSON or YAML: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("The OpenAPI document is not an object.")
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
        if self.method.upper() not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            raise ValueError(f"HTTP method '{self.method}' is not supported.")


def resolve_ref(openapi_spec: dict[str, Any], value: Any) -> Any:
    """What the local ``$ref`` (``#/components/...``) of ``value`` points to,
    else ``value``."""
    ref = value.get("$ref") if isinstance(value, dict) else None
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return value
    target: Any = openapi_spec
    for part in ref[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or key not in target:
            return value
        target = target[key]
    return target


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
    openapi_spec: dict[str, Any], path_item: dict[str, Any], operation: dict[str, Any]
) -> dict[str, Any]:
    """``operation`` with the parameters of its path item and with the local
    references of its parameters and request body resolved."""
    resolved = dict(operation)
    if parameters := operation_parameters(openapi_spec, path_item, operation):
        resolved["parameters"] = parameters
    if "requestBody" in operation:
        resolved["requestBody"] = resolve_ref(openapi_spec, operation["requestBody"])
    return resolved


def openapi_to_method_spec(
    openapi_spec: dict[str, Any],
    path: str,
    path_item: dict[str, Any],
    method_name: str,
    method: dict[str, Any],
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
        spec=resolved_operation(openapi_spec, path_item, method),
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
    resolved as ``resolved_operation`` does. Releases before the
    api_app table read only this shape from ``tool.openapi_schema``."""
    paths: dict[str, dict[str, Any]] = {}
    for path, path_item, method_name, method in openapi_operations(openapi_spec):
        paths.setdefault(path, {})[method_name] = resolved_operation(
            openapi_spec, path_item, method
        )
    return {**openapi_spec, "paths": paths}


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
    for path, path_item, method_name, method in openapi_operations(openapi_spec):
        method_spec = openapi_to_method_spec(
            openapi_spec, path, path_item, method_name, method
        )
        check_unique_name(method_spec, seen_names)
        method_specs.append(method_spec)

    if not method_specs:
        raise ValueError("No methods found in OpenAPI schema")

    return method_specs


def openapi_to_url(openapi_schema: dict[str, dict | str]) -> str:
    """
    Extract URLs from the servers section of an OpenAPI schema.

    Args:
        openapi_schema (Dict[str, Union[Dict, str, List]]): The OpenAPI schema in dictionary format.

    Returns:
        List[str]: A list of base URLs.
    """
    urls: list[str] = []

    servers = cast(list[dict[str, Any]], openapi_schema.get("servers", []))
    for server in servers:
        url = server.get("url")
        if url is not None and not isinstance(url, str):
            raise ValueError("`servers[].url` must be a string")
        if url:
            urls.append(url)

    if len(urls) != 1:
        raise ValueError(
            f"Expected exactly one URL in OpenAPI schema, but found {urls}"
        )

    return urls[0]


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
    if check_server_url and not openapi_to_url(schema):
        raise ValueError("OpenAPI schema does not contain a valid URL in `servers`")

    method_specs = openapi_to_method_specs(schema)
    for method_spec in method_specs:
        method_spec.validate_spec()
