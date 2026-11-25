"""OpenAPI parsing and the import of a spec: a spec that imports also creates."""

import copy
import json
from typing import Any

import pytest
import yaml

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.openapi_endpoints import (
    EndpointLinesError,
    apply_endpoint_lines,
    endpoint_lines,
)
from onyx.integrations.service import import_openapi_document
from onyx.server.features.integrations.models import OpenApiEndpointsRequest
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_method_specs,
    openapi_to_url,
    parse_openapi_document,
    validate_openapi_schema,
)

SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    # No description: the title is enough.
    "info": {"title": "Pets", "version": "1.0"},
    "servers": [{"url": "https://pets.example.com"}],
    "components": {
        "parameters": {
            "petId": {
                "name": "petId",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        }
    },
    "paths": {
        "/pets/{petId}": {
            "summary": "One pet",
            "parameters": [
                {"$ref": "#/components/parameters/petId"},
                {"name": "verbose", "in": "query", "schema": {"type": "boolean"}},
            ],
            "get": {
                "operationId": "getPet",
                "summary": "Read a pet",
                "parameters": [
                    {"name": "verbose", "in": "query", "schema": {"type": "integer"}}
                ],
            },
            "delete": {"operationId": "deletePet", "summary": "Delete a pet"},
        },
        "/pets/{petId}/photo": {
            "post": {
                "operationId": "uploadPhoto",
                "summary": "Upload a photo",
                "parameters": [{"$ref": "#/components/parameters/petId"}],
                "requestBody": {
                    "content": {"application/octet-stream": {"schema": {}}}
                },
            }
        },
    },
}


def _callable_spec() -> dict[str, Any]:
    spec = copy.deepcopy(SPEC)
    del spec["paths"]["/pets/{petId}/photo"]
    return spec


def _import(document: str) -> Any:
    return import_openapi_document(OpenApiEndpointsRequest(openapi_document=document))


def test_path_parameters_apply_to_each_operation() -> None:
    specs = {spec.raw_name: spec for spec in openapi_to_method_specs(SPEC)}

    assert specs["getPet"].spec["parameters"] == [
        SPEC["components"]["parameters"]["petId"],
        # The operation's own parameter wins.
        {"name": "verbose", "in": "query", "schema": {"type": "integer"}},
    ]
    assert [p["name"] for p in specs["deletePet"].spec["parameters"]] == [
        "petId",
        "verbose",
    ]
    assert specs["getPet"].to_tool_definition().parameters["properties"] == {
        "petId": {"type": "string"},
        "verbose": {"type": "integer"},
    }
    # The document stays as it was.
    assert "parameters" not in SPEC["paths"]["/pets/{petId}"]["delete"]


def test_a_spec_with_path_parameters_validates_and_builds_tools() -> None:
    spec = _callable_spec()
    validate_openapi_schema(spec)

    tools = build_custom_tools_from_openapi_schema_and_headers(
        1,
        spec,
        dynamic_schema_info=DynamicSchemaInfo(chat_session_id=None, message_id=None),
    )
    assert sorted(
        tool.integration_action.action for tool in tools if tool.integration_action
    ) == ["deletePet", "getPet"]


def test_import_drops_an_operation_without_a_json_body() -> None:
    view = _import(json.dumps(SPEC))

    assert view.skipped == [
        "POST /pets/{petId}/photo: the body is application/octet-stream, "
        "and only application/json is supported"
    ]
    assert json.loads(view.openapi_document) == _callable_spec()
    assert view.endpoints == [
        "GET /pets/{petId}?verbose Read a pet",
        # The path item gives each operation ?verbose.
        "DELETE /pets/{petId}?verbose Delete a pet",
    ]
    validate_openapi_schema(json.loads(view.openapi_document))


def test_import_keeps_yaml_as_yaml() -> None:
    view = _import(yaml.safe_dump(SPEC, sort_keys=False))

    assert len(view.skipped) == 1
    with pytest.raises(json.JSONDecodeError):
        json.loads(view.openapi_document)
    assert yaml.safe_load(view.openapi_document) == _callable_spec()


def test_import_keeps_the_text_when_it_drops_nothing() -> None:
    document = "# Pets\n" + yaml.safe_dump(_callable_spec(), sort_keys=False)

    view = _import(document)

    assert view.openapi_document == document
    assert view.skipped == []


def test_import_needs_no_server_url() -> None:
    spec = _callable_spec()
    del spec["servers"]

    view = _import(json.dumps(spec))

    assert view.base_url == ""
    assert len(view.endpoints) == 2


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda spec: spec.pop("info"), "`info` section is required"),
        (lambda spec: spec.update(openapi="2.0"), "'2.0' is not supported"),
        (
            lambda spec: spec.update(swagger=spec.pop("openapi")),
            "Swagger 3.0.3 is not supported",
        ),
        (
            lambda spec: spec.update(
                paths={"/pets/{petId}/photo": SPEC["paths"]["/pets/{petId}/photo"]}
            ),
            "No methods found",
        ),
    ],
)
def test_import_refuses_a_spec_that_create_refuses(change: Any, message: str) -> None:
    spec = copy.deepcopy(SPEC)
    change(spec)

    with pytest.raises(OnyxError) as error:
        _import(json.dumps(spec))

    assert error.value.error_code is OnyxErrorCode.VALIDATION_ERROR
    assert message in error.value.detail


@pytest.mark.parametrize("document", ["<html><body>Docs</body></html>", '{"a": 1}'])
def test_import_tells_a_document_that_is_no_spec_apart(document: str) -> None:
    with pytest.raises(OnyxError) as error:
        _import(document)

    assert error.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_yaml_timestamps_stay_text() -> None:
    spec = parse_openapi_document(
        "openapi: 3.0.0\ninfo:\n  title: T\n  x-added: 2015-02-22T20:00:45.000Z\n"
        "  x-day: 2015-02-22\npaths: {}\n"
    )

    assert spec["info"]["x-added"] == "2015-02-22T20:00:45.000Z"
    assert spec["info"]["x-day"] == "2015-02-22"
    json.dumps(spec)


def _apply(spec: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    return parse_openapi_document(
        apply_endpoint_lines(
            json.dumps(spec),
            title="Pets",
            description=None,
            base_url="https://pets.example.com/v2",
            lines=lines,
        )
    )


def test_the_base_url_replaces_each_imported_server() -> None:
    spec = _callable_spec()
    spec["servers"] = [
        {"url": "https://eu.pets.example.com"},
        {"url": "https://us.pets.example.com"},
    ]
    applied = _apply(spec, endpoint_lines(spec))
    assert openapi_to_url(applied) == "https://pets.example.com/v2"


def test_lines_show_and_keep_shared_query_parameters() -> None:
    spec = _callable_spec()
    spec["components"]["parameters"]["limit"] = {
        "name": "limit",
        "in": "query",
        "schema": {"type": "integer"},
    }
    spec["paths"]["/pets"] = {
        "get": {
            "operationId": "listPets",
            "summary": "List pets",
            "parameters": [{"$ref": "#/components/parameters/limit"}],
        }
    }
    lines = endpoint_lines(spec)
    assert "GET /pets?limit List pets" in lines
    assert "GET /pets/{petId}?verbose Read a pet" in lines

    added = _apply(
        spec,
        [line.replace("/pets?limit", "/pets?limit&name") for line in lines]
        + ["PUT /pets/{petId} Replace a pet"],
    )
    assert added["paths"]["/pets"]["get"]["parameters"] == [
        {"$ref": "#/components/parameters/limit"},
        {
            "name": "name",
            "in": "query",
            "required": False,
            "schema": {"type": "string"},
        },
    ]
    # The path item defines petId, so the new operation adds no string copy.
    assert "parameters" not in added["paths"]["/pets/{petId}"]["put"]

    removed = _apply(spec, [line.replace("/pets?limit", "/pets") for line in lines])
    assert "parameters" not in removed["paths"]["/pets"]["get"]

    with pytest.raises(EndpointLinesError, match="Each operation of /pets/{petId}"):
        _apply(spec, [line.replace("?verbose", "") for line in lines])
