"""OpenAPI parsing and the import of a spec: a spec that imports also creates."""

import copy
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.openapi_endpoints import (
    EndpointLinesError,
    _new_operation_id,
    apply_endpoint_lines,
    endpoint_lines,
)
from onyx.integrations.service import _openapi_document, import_openapi_document
from onyx.server.features.integrations.models import (
    OpenApiConfigInput,
    OpenApiEndpointsRequest,
)
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    _MAX_INLINED_NODES,
    REQUEST_BODY,
    inline_path_parameters,
    openapi_to_method_specs,
    openapi_to_url,
    parse_openapi_document,
    validate_openapi_schema,
)
from tests.unit.fakes import NO_CREDENTIALS

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


def test_a_request_body_reference_is_resolved() -> None:
    body = {
        "required": True,
        "content": {"application/json": {"schema": {"type": "object"}}},
    }
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Pets", "version": "1.0"},
        "servers": [{"url": "https://pets.example.com"}],
        "components": {"requestBodies": {"Pet": body}},
        "paths": {
            "/pets": {
                "post": {
                    "operationId": "addPet",
                    "summary": "Add a pet",
                    "requestBody": {"$ref": "#/components/requestBodies/Pet"},
                }
            }
        },
    }

    (method_spec,) = openapi_to_method_specs(spec)

    assert method_spec.to_tool_definition().parameters["properties"] == {
        REQUEST_BODY: {"type": "object"}
    }
    assert inline_path_parameters(spec)["paths"]["/pets"]["post"]["requestBody"] == (
        body
    )


def test_schema_references_are_inlined_into_the_tool() -> None:
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Pets", "version": "1.0"},
        "servers": [{"url": "https://pets.example.com"}],
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "owner": {"$ref": "#/components/schemas/Owner"},
                        "parent": {"$ref": "#/components/schemas/Pet"},
                        "toy": {"$ref": "#/components/schemas/Missing"},
                    },
                },
                "Owner": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "Kind": {"type": "string", "enum": ["cat", "dog"]},
            }
        },
        "paths": {
            "/pets/{kind}": {
                "post": {
                    "operationId": "addPet",
                    "summary": "Add a pet",
                    "parameters": [
                        {
                            "name": "kind",
                            "in": "path",
                            "required": True,
                            "schema": {"$ref": "#/components/schemas/Kind"},
                        }
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        }
                    },
                }
            }
        },
    }

    (method_spec,) = openapi_to_method_specs(spec)

    properties = method_spec.to_tool_definition().parameters["properties"]
    assert properties == {
        REQUEST_BODY: {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "owner": {"type": "object", "properties": {"id": {"type": "integer"}}},
                # A cycle and a missing reference admit any value.
                "parent": {},
                "toy": {},
            },
        },
        "kind": {"type": "string", "enum": ["cat", "dog"]},
    }
    assert "$ref" not in json.dumps(inline_path_parameters(spec)["paths"])

    (tool,) = build_custom_tools_from_openapi_schema_and_headers(
        1,
        spec,
        dynamic_schema_info=DynamicSchemaInfo(chat_session_id=None, message_id=None),
        headers={},
        credentials=NO_CREDENTIALS,
    )
    body = {"name": "Rex", "owner": {"id": 7}}
    assert tool._request({"kind": "dog", REQUEST_BODY: body}) == (
        "post",
        "https://pets.example.com/pets/dog",
        body,
    )


def test_pointers_into_lists_and_with_escapes_resolve() -> None:
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Pets", "version": "1.0"},
        "servers": [{"url": "https://pets.example.com"}],
        "components": {
            "schemas": {
                "Pet": {
                    "allOf": [
                        {
                            "type": "object",
                            "properties": {
                                "kind": {"$ref": "#/components/schemas/a~1b"},
                                "size": {"$ref": "#/components/schemas/pet%20size"},
                                "tag": {"$ref": "#/components/schemas/t~0x"},
                            },
                        }
                    ]
                },
                "a/b": {"type": "string"},
                "pet size": {"type": "integer"},
                "t~x": {"type": "boolean"},
            }
        },
        "paths": {
            "/pets": {
                "post": {
                    "operationId": "addPet",
                    "summary": "Add a pet",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet/allOf/0"}
                            }
                        }
                    },
                }
            }
        },
    }

    (method_spec,) = openapi_to_method_specs(spec)

    assert method_spec.to_tool_definition().parameters["properties"] == {
        REQUEST_BODY: {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "size": {"type": "integer"},
                "tag": {"type": "boolean"},
            },
        }
    }


def _exploding_spec() -> dict[str, Any]:
    """Each schema refers to the one below it twice, so the body inlines to
    about 2**20 values."""
    schemas: dict[str, Any] = {"S0": {"type": "string"}}
    for i in range(1, 21):
        below = {"$ref": f"#/components/schemas/S{i - 1}"}
        schemas[f"S{i}"] = {"type": "object", "properties": {"a": below, "b": below}}
    return {
        "openapi": "3.0.3",
        "info": {"title": "Big", "version": "1.0"},
        "servers": [{"url": "https://big.example.com"}],
        "components": {"schemas": schemas},
        "paths": {
            "/things": {
                "post": {
                    "operationId": "addThing",
                    "summary": "Add a thing",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/S20"}
                            }
                        }
                    },
                }
            }
        },
    }


def _count_values(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + sum(_count_values(item) for item in value.values())
    if isinstance(value, list):
        return 1 + sum(_count_values(item) for item in value)
    return 1


def test_a_spec_that_expands_too_far_keeps_its_tools_and_later_refs() -> None:
    spec = _exploding_spec()
    # Two operations share one budget.
    spec["paths"]["/other"] = {"post": copy.deepcopy(spec["paths"]["/things"]["post"])}
    spec["paths"]["/other"]["post"]["operationId"] = "addOther"

    tools = build_custom_tools_from_openapi_schema_and_headers(
        1,
        spec,
        dynamic_schema_info=DynamicSchemaInfo(chat_session_id=None, message_id=None),
        headers={},
        credentials=NO_CREDENTIALS,
    )

    assert sorted(t.name for t in tools) == [
        "custom__1__addOther",
        "custom__1__addThing",
    ]
    definitions = [t.tool_definition().parameters for t in tools]
    # Past the budget, the references stay as written.
    assert all('"$ref"' in json.dumps(d) for d in definitions)
    # The copies stay within the budget; the rest is the spec's own small
    # schemas, at most a few values for each level of the chain.
    assert sum(_count_values(d) for d in definitions) <= _MAX_INLINED_NODES + 1000


def test_server_variables_take_their_defaults() -> None:
    spec = _callable_spec()
    spec["servers"] = [
        {
            "url": "https://pets.example.com/{version}",
            "variables": {"version": {"default": "v2"}},
        }
    ]

    assert _import(json.dumps(spec)).base_url == "https://pets.example.com/v2"
    tools = build_custom_tools_from_openapi_schema_and_headers(
        1,
        spec,
        dynamic_schema_info=DynamicSchemaInfo(chat_session_id=None, message_id=None),
        headers={},
        credentials=NO_CREDENTIALS,
    )
    assert {tool._base_url for tool in tools} == {"https://pets.example.com/v2"}
    # With no default, the admin sets the base URL.
    del spec["servers"][0]["variables"]["version"]["default"]
    assert openapi_to_url(spec) == "https://pets.example.com/{version}"


def test_a_trailing_slash_on_the_server_url_makes_no_double_slash() -> None:
    spec: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Users", "version": "1.0"},
        "servers": [{"url": "https://api.example.com/v1/"}],
        "paths": {
            "/users": {"get": {"operationId": "listUsers", "summary": "List users"}}
        },
    }

    (method_spec,) = openapi_to_method_specs(spec)
    assert (
        method_spec.build_url(openapi_to_url(spec), {}, {})
        == "https://api.example.com/v1/users"
    )


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


def test_import_of_only_uncallable_operations_gives_no_endpoints() -> None:
    spec = copy.deepcopy(SPEC)
    spec["paths"] = {"/pets/{petId}/photo": SPEC["paths"]["/pets/{petId}/photo"]}

    view = _import(json.dumps(spec))

    assert view.endpoints == []
    assert [line.split(":")[0] for line in view.skipped] == ["POST /pets/{petId}/photo"]


def test_a_save_refuses_an_entry_that_is_not_an_object() -> None:
    """The parser skips such an entry, so a save would drop its action."""
    operation = _callable_spec()
    operation["paths"]["/pets/{petId}"]["get"] = None
    with pytest.raises(ValueError, match=r"GET /pets/\{petId\} must be an object"):
        validate_openapi_schema(operation)

    path_item = _callable_spec()
    path_item["paths"]["/owners"] = "owners"
    with pytest.raises(ValueError, match="path item of /owners must be an object"):
        validate_openapi_schema(path_item)


def test_import_drops_and_lists_an_entry_that_is_not_an_object() -> None:
    spec = _callable_spec()
    spec["paths"]["/pets/{petId}"]["get"] = None
    spec["paths"]["/owners"] = "owners"

    view = _import(json.dumps(spec))

    assert view.skipped == [
        "GET /pets/{petId}: it is not an object",
        "The path item of /owners: it is not an object",
    ]
    assert view.endpoints == ["DELETE /pets/{petId}?verbose Delete a pet"]
    validate_openapi_schema(json.loads(view.openapi_document))


def test_import_lists_a_path_item_reference() -> None:
    spec = _callable_spec()
    spec["components"]["pathItems"] = {"Owners": {"get": {"operationId": "owners"}}}
    spec["paths"]["/owners"] = {"$ref": "#/components/pathItems/Owners"}

    view = _import(json.dumps(spec))

    assert view.skipped == ["The path item of /owners: its $ref is not supported"]
    assert "/owners" not in json.loads(view.openapi_document)["paths"]


def test_extensions_under_paths_are_not_endpoints() -> None:
    """OpenAPI allows ``x-*`` keys under ``paths`` with any value."""
    spec = _callable_spec()
    spec["paths"]["x-tags"] = ["pets"]
    spec["paths"]["x-internal"] = False
    spec["paths"]["x-owners"] = {"$ref": "#/components/pathItems/Owners"}
    validate_openapi_schema(spec)

    view = _import(json.dumps(spec))

    assert view.skipped == []
    paths = json.loads(view.openapi_document)["paths"]
    assert paths["x-tags"] == ["pets"]
    assert paths["x-owners"] == {"$ref": "#/components/pathItems/Owners"}


def test_import_needs_no_server_url() -> None:
    spec = _callable_spec()
    del spec["servers"]

    view = _import(json.dumps(spec))

    assert view.base_url == ""
    assert len(view.endpoints) == 2


@pytest.mark.parametrize("servers", [None, "https://pets.example.com", ["x"], [None]])
def test_import_refuses_servers_of_the_wrong_shape(servers: Any) -> None:
    spec = _callable_spec()
    spec["servers"] = servers

    with pytest.raises(OnyxError) as error:
        _import(json.dumps(spec))

    assert error.value.error_code is OnyxErrorCode.VALIDATION_ERROR
    assert "`servers`" in error.value.detail


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda spec: spec.pop("info"), "`info` section is required"),
        (lambda spec: spec.update(openapi="2.0"), "'2.0' is not supported"),
        (
            lambda spec: spec.update(swagger=spec.pop("openapi")),
            "Swagger 3.0.3 is not supported",
        ),
        (lambda spec: spec.update(paths=None), "`paths` in OpenAPI schema must be"),
        (lambda spec: spec.update(paths=[]), "`paths` in OpenAPI schema must be"),
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


def test_import_refuses_an_unpaired_surrogate() -> None:
    spec = _callable_spec()
    spec["info"] = {**spec.get("info", {}), "description": "\ud800"}

    with pytest.raises(OnyxError, match="unpaired Unicode surrogate") as error:
        _import(json.dumps(spec))

    assert error.value.error_code is OnyxErrorCode.VALIDATION_ERROR


def test_a_pasted_spec_has_the_size_limit_of_a_spec_url() -> None:
    spec = _callable_spec()
    spec["info"]["description"] = "x" * (5 * 1024 * 1024)

    with pytest.raises(OnyxError, match="larger than 5 MB"):
        _import(json.dumps(spec))


def test_lines_that_grow_the_stored_spec_over_5_mb_are_refused() -> None:
    spec = _callable_spec()
    spec["info"]["description"] = "x" * (4 * 1024 * 1024)
    lines = [f"GET /pets{i} Name{'y' * 2000}" for i in range(800)]

    with pytest.raises(OnyxError) as error:
        _openapi_document(
            OpenApiConfigInput(base_url="https://pets.example.com", endpoints=lines),
            json.dumps(spec),
            title="Pets",
            description=None,
        )

    assert error.value.error_code is OnyxErrorCode.PAYLOAD_TOO_LARGE


@pytest.mark.parametrize("char", ["x", "é"])
def test_removing_a_line_from_a_compact_spec_near_5_mb_saves(char: str) -> None:
    spec = _callable_spec()
    spec["info"]["description"] = ""
    room = 5 * 1024 * 1024 - len(json.dumps(spec, separators=(",", ":")))
    spec["info"]["description"] = char * ((room - 10) // len(char.encode()))
    stored = json.dumps(spec, separators=(",", ":"), ensure_ascii=False)
    lines = [line for line in endpoint_lines(spec) if "DELETE" not in line]

    document, saved = _openapi_document(
        OpenApiConfigInput(base_url="https://pets.example.com", endpoints=lines),
        stored,
        title="Pets",
        description=None,
    )

    assert "delete" not in saved["paths"]["/pets/{petId}"]
    assert "\n" not in document


def test_a_fetched_spec_with_a_query_in_its_server_url_is_refused() -> None:
    spec = _callable_spec()
    spec["servers"] = [{"url": "https://pets.example.com/api?key=1"}]
    response = MagicMock(status_code=200, headers={})
    response.raw.read1.side_effect = [json.dumps(spec).encode(), b""]
    fetch = MagicMock()
    fetch.return_value.__enter__.return_value = response

    with (
        patch("onyx.integrations.service.get_security_settings"),
        patch("onyx.integrations.service.outbound_ssrf_params"),
        patch("onyx.integrations.service.ssrf_safe_get", fetch),
        pytest.raises(OnyxError, match="cannot have a query") as error,
    ):
        import_openapi_document(
            OpenApiEndpointsRequest(spec_url="https://pets.example.com/openapi.json")
        )

    assert error.value.error_code is OnyxErrorCode.VALIDATION_ERROR


def test_yaml_timestamps_stay_text() -> None:
    spec = parse_openapi_document(
        "openapi: 3.0.0\ninfo:\n  title: T\n  x-added: 2015-02-22T20:00:45.000Z\n"
        "  x-day: 2015-02-22\npaths: {}\n"
    )

    assert spec["info"]["x-added"] == "2015-02-22T20:00:45.000Z"
    assert spec["info"]["x-day"] == "2015-02-22"
    json.dumps(spec)


def test_yaml_reads_as_the_same_json() -> None:
    """YAML 1.2: on, off, yes and no are text; true and false are booleans."""
    spec = parse_openapi_document(
        "openapi: 3.0.0\ninfo: {title: T}\npaths: {}\n"
        "x-switch: {type: string, enum: [on, off, yes, no], nullable: true}\n"
        "x-flags: [True, FALSE]\n"
    )

    assert spec["x-switch"] == {
        "type": "string",
        "enum": ["on", "off", "yes", "no"],
        "nullable": True,
    }
    assert spec["x-flags"] == [True, False]


def test_a_yaml_value_that_is_not_json_is_refused_at_import() -> None:
    with pytest.raises(ValueError, match="not JSON"):
        parse_openapi_document(
            "openapi: 3.0.0\ninfo: {title: T}\npaths: {}\nx-tags: !!set {a, b}\n"
        )
    with pytest.raises(OnyxError) as error:
        import_openapi_document(
            OpenApiEndpointsRequest(
                openapi_document="openapi: 3.0.0\ninfo: {title: T}\n"
                "paths: {}\nx-tags: !!set {a, b}\n"
            )
        )
    assert error.value.error_code is OnyxErrorCode.INVALID_INPUT


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


def test_a_line_with_a_dotted_path_parameter_saves_and_builds_its_url() -> None:
    saved = _apply(
        _callable_spec(),
        [*endpoint_lines(_callable_spec()), "GET /orders/{order.id} Get an order"],
    )

    validate_openapi_schema(saved)
    order = next(
        spec
        for spec in openapi_to_method_specs(saved)
        if spec.path == "/orders/{order.id}"
    )
    assert (
        order.build_url("https://pets.example.com/v2", {"order.id": "a/b"}, {})
        == "https://pets.example.com/v2/orders/a%2Fb"
    )


def test_the_base_url_replaces_each_imported_server() -> None:
    spec = _callable_spec()
    spec["servers"] = [
        {"url": "https://eu.pets.example.com"},
        {"url": "https://us.pets.example.com"},
    ]
    applied = _apply(spec, endpoint_lines(spec))
    assert openapi_to_url(applied) == "https://pets.example.com/v2"


def test_a_line_sent_as_shown_keeps_an_operation_it_cannot_write() -> None:
    """A stored operation can have a line that does not parse back to it,
    such as one with no name. A save that sends its line unchanged keeps it
    as stored, also when other lines change. A space in a query name shows as
    %20."""
    spec = _callable_spec()
    reports = {
        "get": {
            "operationId": "listReports",
            "summary": "List reports",
            "parameters": [
                {"name": "search term", "in": "query", "schema": {"type": "string"}}
            ],
        }
    }
    unnamed = {"get": {"operationId": "ping"}}
    spec["paths"]["/reports"] = reports
    spec["paths"]["/ping"] = unnamed
    lines = endpoint_lines(spec)
    assert "GET /reports?search%20term List reports" in lines

    base_url_only = _apply(spec, lines)
    assert base_url_only["paths"]["/reports"] == reports
    assert base_url_only["paths"]["/ping"] == unnamed

    other_edited = _apply(
        spec,
        [line for line in lines if not line.startswith("DELETE /pets/{petId}")]
        + ["POST /reports Add a report"],
    )
    assert other_edited["paths"]["/reports"]["get"] == reports["get"]
    assert other_edited["paths"]["/ping"] == unnamed
    assert "delete" not in other_edited["paths"]["/pets/{petId}"]
    assert "post" in other_edited["paths"]["/reports"]

    label_edited = _apply(
        spec, [line.replace("List reports", "Find reports") for line in lines]
    )
    assert label_edited["paths"]["/reports"]["get"] == {
        **reports["get"],
        "summary": "Find reports",
    }


def test_lines_save_over_an_operation_with_malformed_parameters() -> None:
    """A removed operation with malformed parameters does not break the
    save. A line that edits it gets a line error."""
    spec = _callable_spec()
    spec["paths"]["/broken"] = {"get": {"operationId": "broken", "parameters": 5}}
    kept = endpoint_lines(_callable_spec())

    saved = _apply(spec, kept)

    assert "/broken" not in saved["paths"]
    with pytest.raises(EndpointLinesError, match="Line 3: The parameters of GET"):
        _apply(spec, [*kept, "GET /broken Read it"])


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
        + ["PUT /pets/{petId}?verbose Replace a pet"],
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
    # A new operation also gets the query parameters of its path item.
    with pytest.raises(EndpointLinesError, match="Each operation of /pets/{petId}"):
        _apply(spec, [*lines, "PUT /pets/{petId} Replace a pet"])


def test_a_replacing_operation_keeps_the_parameters_of_its_path() -> None:
    spec = _callable_spec()
    spec["paths"] = {
        "/things/{id}": {
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer"},
                }
            ],
            "get": {"operationId": "getThing", "summary": "Read a thing"},
        }
    }

    replaced = _apply(spec, ["PUT /things/{id} Replace a thing"])

    item = replaced["paths"]["/things/{id}"]
    assert set(item) == {"parameters", "put"}
    assert item["parameters"] == spec["paths"]["/things/{id}"]["parameters"]
    validate_openapi_schema(replaced)


def test_a_line_for_a_path_that_is_not_an_object_is_refused() -> None:
    spec = _callable_spec()
    spec["paths"]["/broken"] = "not an object"

    with pytest.raises(EndpointLinesError, match="/broken in the spec"):
        _apply(spec, ["GET /broken Read it"])


def test_a_line_with_a_fragment_in_its_path_is_refused() -> None:
    with pytest.raises(EndpointLinesError, match="must not have a #"):
        _apply(_callable_spec(), ["POST /tickets#archive Archive tickets"])
    added = _apply(_callable_spec(), ["POST /tickets%23archive Archive tickets"])
    assert "post" in added["paths"]["/tickets%23archive"]


def test_a_new_line_does_not_take_the_key_of_a_removed_operation() -> None:
    """The key of a removed operation keeps its stored policies."""
    spec = _callable_spec()
    spec["paths"] = {
        "/safe": {
            "get": {
                "operationId": _new_operation_id("DELETE", "/everything"),
                "summary": "Read safely",
            }
        }
    }

    with pytest.raises(EndpointLinesError, match="already has the action key"):
        _apply(spec, ["DELETE /everything Delete everything"])


def test_imported_lines_with_any_query_name_save_again() -> None:
    """A spec's query names (`$filter`, `fields[user]`) appear in the lines,
    and those lines save again unchanged."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Orders", "version": "1"},
        "servers": [{"url": "https://orders.example.com"}],
        "paths": {
            "/orders": {
                "get": {
                    "operationId": "list_orders",
                    "summary": "List orders",
                    "parameters": [
                        {
                            "name": "$filter",
                            "in": "query",
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "fields[user]",
                            "in": "query",
                            "schema": {"type": "string"},
                        },
                    ],
                }
            }
        },
    }
    lines = endpoint_lines(spec)
    assert lines == ["GET /orders?$filter&fields[user] List orders"]

    saved = apply_endpoint_lines(
        json.dumps(spec),
        title="Orders",
        description=None,
        base_url="https://orders.example.com",
        lines=lines,
    )

    assert endpoint_lines(json.loads(saved)) == lines


def test_lines_save_over_a_spec_with_an_operation_id_that_is_not_text() -> None:
    spec = _callable_spec()
    spec["paths"]["/pets/{petId}"]["delete"]["operationId"] = ["deletePet"]

    saved = _apply(spec, ["GET /pets/{petId}?verbose Read a pet", "GET /cats Cats"])

    assert "/cats" in saved["paths"]


def test_import_keeps_an_operation_with_a_numbered_path_parameter() -> None:
    spec = _callable_spec()
    spec["paths"]["/{0}"] = {
        "get": {
            "operationId": "byNumber",
            "summary": "By number",
            "parameters": [{"name": "0", "in": "path", "required": True, "schema": {}}],
        }
    }

    view = _import(json.dumps(spec))

    assert view.skipped == []
    assert json.loads(view.openapi_document) == spec


def test_a_yaml_alias_is_refused() -> None:
    nested = "a: &a [x, x]\n" + "".join(
        f"{chr(98 + i)}: &{chr(98 + i)} [*{chr(97 + i)}, *{chr(97 + i)}]\n"
        for i in range(3)
    )

    with pytest.raises(ValueError, match="aliases"):
        parse_openapi_document(nested)
    assert parse_openapi_document("openapi: 3.0.0\nx: &a 1\n")["x"] == 1


@pytest.mark.parametrize(
    "document", ["[" * 100_000, "x: " + "[" * 100_000], ids=["json", "yaml"]
)
def test_a_deeply_nested_document_is_refused(document: str) -> None:
    with pytest.raises(ValueError, match="nested too deeply"):
        parse_openapi_document(document)


def test_a_yaml_duplicate_key_is_refused() -> None:
    document = (
        "openapi: 3.0.0\n"
        "paths:\n"
        "  /pets:\n"
        "    get: {summary: List pets}\n"
        "  /pets:\n"
        "    delete: {summary: Delete pets}\n"
    )

    with pytest.raises(ValueError, match="duplicate key '/pets'"):
        parse_openapi_document(document)
