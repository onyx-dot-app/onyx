from pydantic import JsonValue

from onyx.llm.strict_schema import drop_optional_nulls, strict_schema


def test_optional_properties_become_required_and_nullable() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "default": "x"},
            "limit": {"type": "integer"},
            "shape": {"type": "string", "enum": ["square", "wide"]},
            "id": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        },
        "required": ["query"],
    }
    assert strict_schema(schema) == {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": ["integer", "null"]},
            "shape": {"type": ["string", "null"], "enum": ["square", "wide", None]},
            "id": {
                "anyOf": [
                    {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                    {"type": "null"},
                ]
            },
        },
        "required": ["query", "limit", "shape", "id"],
        "additionalProperties": False,
    }


def test_nested_objects_and_arrays_of_objects() -> None:
    item: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
        "required": ["a"],
    }
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": item}},
        "required": ["items"],
    }
    converted = strict_schema(schema)
    assert converted is not None
    properties = converted["properties"]
    assert isinstance(properties, dict)
    assert properties["items"] == {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": ["number", "null"]},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    }


def test_incompatible_schemas_return_none() -> None:
    def wrap(prop: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return {"type": "object", "properties": {"p": prop}, "required": ["p"]}

    assert strict_schema(wrap({"type": "object", "additionalProperties": True})) is None
    assert strict_schema(wrap({"type": "object"})) is None
    assert strict_schema(wrap({"type": "object", "patternProperties": {}})) is None
    assert strict_schema(wrap({"oneOf": [{"type": "string"}]})) is None
    assert strict_schema(wrap({"type": "array"})) is None
    assert strict_schema(wrap({"description": "any value"})) is None
    assert strict_schema({"anyOf": [{"type": "object"}]}) is None


def test_drop_optional_nulls_keeps_required_and_unknown_nulls() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "q": {"type": ["string", "null"]},
            "n": {"type": "integer"},
            "rows": {
                "type": "array",
                "items": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
        },
        "required": ["q"],
    }
    arguments: dict[str, JsonValue] = {
        "q": None,
        "n": None,
        "rows": [{"x": None}],
        "extra": None,
    }
    assert drop_optional_nulls(arguments, schema) == {
        "q": None,
        "rows": [{}],
        "extra": None,
    }
