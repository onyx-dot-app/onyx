"""Convert tool parameter schemas to OpenAI strict function-calling form."""

from typing import cast

from pydantic import JsonValue

JsonSchema = dict[str, JsonValue]

# Keywords OpenAI strict mode accepts; anything else makes the tool non-strict.
_ALLOWED_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "anyOf",
        "enum",
        "const",
        "description",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
    }
)
# Annotations with no effect on validation that strict mode may reject.
_DROPPED_KEYWORDS = frozenset({"default", "examples", "title", "$schema"})
_SUPPORTED_FORMATS = frozenset(
    {
        "date-time",
        "time",
        "date",
        "duration",
        "email",
        "hostname",
        "ipv4",
        "ipv6",
        "uuid",
    }
)
_MAX_DEPTH = 10


class _NotStrictCompatible(Exception):
    pass


def _nullable(schema: JsonSchema) -> JsonSchema:
    declared = schema.get("type")
    if isinstance(declared, (str, list)) and "anyOf" not in schema:
        types = [declared] if isinstance(declared, str) else list(declared)
        enum = schema.get("enum")
        nullable: JsonSchema = {**schema, "type": [*types, "null"]}
        if isinstance(enum, list) and None not in enum:
            nullable["enum"] = [*enum, None]
        return nullable if "null" not in types else schema
    return {"anyOf": [schema, {"type": "null"}]}


def _convert(schema: JsonValue, depth: int) -> JsonSchema:
    if not isinstance(schema, dict) or depth > _MAX_DEPTH:
        raise _NotStrictCompatible()
    unknown = schema.keys() - _ALLOWED_KEYWORDS - _DROPPED_KEYWORDS
    if unknown or not schema.keys() & {"type", "anyOf", "enum", "const"}:
        raise _NotStrictCompatible()
    result: JsonSchema = {
        key: value for key, value in schema.items() if key in _ALLOWED_KEYWORDS
    }
    if result.get("format") not in _SUPPORTED_FORMATS:
        result.pop("format", None)
    declared = schema.get("type")
    is_object = declared == "object" or (
        isinstance(declared, list) and "object" in declared
    )
    properties = schema.get("properties")
    if is_object or properties is not None:
        if not isinstance(properties, dict) or schema.get(
            "additionalProperties", False
        ):
            raise _NotStrictCompatible()
        required = schema.get("required") or []
        result["properties"] = {
            name: _convert(prop, depth + 1)
            if name in cast(list[JsonValue], required)
            else _nullable(_convert(prop, depth + 1))
            for name, prop in properties.items()
        }
        result["required"] = list(properties)
        result["additionalProperties"] = False
    if declared == "array" and "items" not in schema:
        raise _NotStrictCompatible()
    if "items" in schema:
        result["items"] = _convert(schema["items"], depth + 1)
    any_of = schema.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list):
            raise _NotStrictCompatible()
        result["anyOf"] = [_convert(option, depth + 1) for option in any_of]
    return result


def strict_schema(schema: JsonSchema) -> JsonSchema | None:
    """Return a strict-mode copy of a tool's parameters, or None if impossible.

    Optional properties become required and nullable; callers must treat a null
    for an originally optional property as absent.
    """
    if schema.get("type") != "object":
        return None
    try:
        return _convert(schema, 0)
    except _NotStrictCompatible:
        return None


def drop_optional_nulls(value: JsonValue, schema: JsonValue) -> JsonValue:
    """Remove nulls a strict schema forced onto properties the original schema
    left optional, so tools see those properties as absent."""
    if not isinstance(schema, dict):
        return value
    properties = schema.get("properties")
    if isinstance(value, dict) and isinstance(properties, dict):
        required = schema.get("required")
        required_names = required if isinstance(required, list) else []
        return {
            name: drop_optional_nulls(item, properties.get(name))
            for name, item in value.items()
            if item is not None or name in required_names or name not in properties
        }
    if isinstance(value, list) and "items" in schema:
        return [drop_optional_nulls(item, schema["items"]) for item in value]
    return value
