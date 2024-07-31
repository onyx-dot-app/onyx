from typing import Any
from typing import cast

from pydantic import BaseModel

REQUEST_BODY = "requestBody"


class PathSpec(BaseModel):
    path: str
    methods: dict[str, Any]


class MethodSpec(BaseModel):
    name: str
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
                f"Unsupported content type: '{list(content.keys())[0]}'. "
                f"Only 'application/json' is supported."
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
        self, base_url: str, path_params: dict[str, str], query_params: dict[str, str]
    ) -> str:
        url = f"{base_url}{self.path}"
        try:
            url = url.format(**path_params)
        except KeyError as e:
            raise ValueError(f"Missing path parameter: {e}")
        if query_params:
            url += "?"
            for param, value in query_params.items():
                url += f"{param}={value}&"
            url = url[:-1]
        return url

    def to_tool_definition(self) -> dict[str, Any]:
        tool_definition: Any = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.summary,
                "parameters": {"type": "object", "properties": {}},
            },
        }

        request_body_schema = self.get_request_body_schema()
        if request_body_schema:
            tool_definition["function"]["parameters"]["properties"][
                REQUEST_BODY
            ] = request_body_schema

        query_param_schemas = self.get_query_param_schemas()
        if query_param_schemas:
            tool_definition["function"]["parameters"]["properties"].update(
                {param["name"]: param["schema"] for param in query_param_schemas}
            )

        path_param_schemas = self.get_path_param_schemas()
        if path_param_schemas:
            tool_definition["function"]["parameters"]["properties"].update(
                {param["name"]: param["schema"] for param in path_param_schemas}
            )
        return tool_definition

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


"""Path-level utils"""


def openapi_to_path_specs(openapi_spec: dict[str, Any]) -> list[PathSpec]:
    path_specs = []

    for path, methods in openapi_spec.get("paths", {}).items():
        path_specs.append(PathSpec(path=path, methods=methods))

    return path_specs


"""Method-level utils"""


def openapi_to_method_specs(openapi_spec: dict[str, Any]) -> list[MethodSpec]:
    path_specs = openapi_to_path_specs(openapi_spec)

    method_specs = []
    for path_spec in path_specs:
        for method_name, method in path_spec.methods.items():
            name = method.get("operationId")
            if not name:
                raise ValueError(
                    f"Operation ID is not specified for {method_name.upper()} {path_spec.path}"
                )

            summary = method.get("summary") or method.get("description")
            if not summary:
                raise ValueError(
                    f"Summary is not specified for {method_name.upper()} {path_spec.path}"
                )

            method_specs.append(
                MethodSpec(
                    name=name,
                    summary=summary,
                    path=path_spec.path,
                    method=method_name,
                    spec=method,
                )
            )

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
        if url:
            urls.append(url)

    if len(urls) != 1:
        raise ValueError(
            f"Expected exactly one URL in OpenAPI schema, but found {urls}"
        )

    return urls[0]


def validate_openapi_schema(schema: dict[str, Any]) -> None:
    """
    Validate the given JSON schema as an OpenAPI schema.

    Parameters:
    - schema (dict): The JSON schema to validate.

    Returns:
    - bool: True if the schema is valid, False otherwise.
    """

    # check basic structure
    if "info" not in schema:
        raise ValueError("`info` section is required in OpenAPI schema")

    info = schema["info"]
    if "title" not in info:
        raise ValueError("`title` is required in `info` section of OpenAPI schema")
    if "description" not in info:
        raise ValueError(
            "`description` is required in `info` section of OpenAPI schema"
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

    url = openapi_to_url(schema)
    if not url:
        raise ValueError("OpenAPI schema does not contain a valid URL in `servers`")

    method_specs = openapi_to_method_specs(schema)
    for method_spec in method_specs:
        method_spec.validate_spec()
