"""Convert tool parameter schemas to OpenAI strict function-calling form."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import cast

from pydantic import JsonValue

JsonSchema = dict[str, JsonValue]


@dataclass(frozen=True)
class PreparedTools:
    tools: list[dict[str, JsonValue]] = field(default_factory=list)
    strict_names: frozenset[str] = frozenset()


@dataclass
class ToolSchemaState:
    """The schemas selected for one request and their argument restoration."""

    active: PreparedTools = field(default_factory=PreparedTools)


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
_SCHEMA_TYPES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)
_MAX_DEPTH = 10


class _NotStrictCompatible(Exception):
    pass


def _nullable(schema: JsonSchema) -> JsonSchema:
    declared = schema.get("type")
    if (
        isinstance(declared, (str, list))
        and "anyOf" not in schema
        and "const" not in schema
    ):
        types = [declared] if isinstance(declared, str) else list(declared)
        enum = schema.get("enum")
        nullable: JsonSchema = {
            **schema,
            "type": types if "null" in types else [*types, "null"],
        }
        if isinstance(enum, list) and None not in enum:
            nullable["enum"] = [*enum, None]
        return nullable
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
    if "format" in result and (
        not isinstance(result["format"], str)
        or result["format"] not in _SUPPORTED_FORMATS
    ):
        raise _NotStrictCompatible()
    declared = schema.get("type")
    if "type" in schema:
        types = declared if isinstance(declared, list) else [declared]
        if (
            not types
            or any(
                not isinstance(name, str) or name not in _SCHEMA_TYPES for name in types
            )
            or len(set(types)) != len(types)
        ):
            raise _NotStrictCompatible()
    is_object = declared == "object" or (
        isinstance(declared, list) and "object" in declared
    )
    properties = schema.get("properties")
    if is_object or properties is not None:
        if (
            not isinstance(properties, dict)
            or schema.get("additionalProperties", False) is not False
        ):
            raise _NotStrictCompatible()
        required = schema.get("required", [])
        if not isinstance(required, list) or any(
            not isinstance(name, str) or name not in properties for name in required
        ):
            raise _NotStrictCompatible()
        for name, prop in properties.items():
            if name not in required and _accepts_null(prop):
                # Null and omission are distinct inputs; do not collapse them.
                raise _NotStrictCompatible()
        result["properties"] = {
            name: _convert(prop, depth + 1)
            if name in cast(list[JsonValue], required)
            else _nullable(_convert(prop, depth + 1))
            for name, prop in properties.items()
        }
        result["required"] = list(properties)
        result["additionalProperties"] = False
    if (
        declared == "array" or isinstance(declared, list) and "array" in declared
    ) and "items" not in schema:
        raise _NotStrictCompatible()
    if "items" in schema:
        result["items"] = _convert(schema["items"], depth + 1)
    any_of = schema.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list):
            raise _NotStrictCompatible()
        # Object alternatives need branch-aware restoration of omitted fields.
        if any(
            isinstance(option, dict)
            and (
                "properties" in option
                or option.get("type") in ("object", "array")
                or isinstance(option.get("type"), list)
                and any(t in ("object", "array") for t in option["type"])
            )
            for option in any_of
        ):
            raise _NotStrictCompatible()
        result["anyOf"] = [_convert(option, depth + 1) for option in any_of]
    return result


def _accepts_null(schema: JsonValue) -> bool:
    if not isinstance(schema, dict):
        return True
    if "const" in schema:
        return schema["const"] is None
    enum = schema.get("enum")
    if isinstance(enum, list) and None not in enum:
        return False
    options = schema.get("anyOf")
    if isinstance(options, list):
        return any(_accepts_null(option) for option in options)
    declared = schema.get("type")
    return (
        declared is None
        or declared == "null"
        or isinstance(declared, list)
        and "null" in declared
    )


def strict_schema(schema: JsonSchema) -> JsonSchema | None:
    """Return a strict-mode copy of a tool's parameters, or None if impossible.

    Optional properties become required and nullable; callers must treat a null
    for an originally optional property as absent.
    """
    if schema.get("type") != "object":
        return None
    try:
        return _convert(deepcopy(schema), 0)
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


def prepare_strict_tools(
    tools: list[dict[str, JsonValue]], *, enabled: bool = True
) -> PreparedTools:
    """Copy compatible function schemas and identify their response normalizers."""
    result: list[dict[str, JsonValue]] = []
    names: set[str] = set()
    for tool in tools:
        function = tool.get("function")
        if not isinstance(function, dict) or function.get("strict") is not None:
            result.append(tool)
            continue
        parameters = function.get("parameters")
        name = function.get("name")
        converted = (
            strict_schema(parameters)
            if enabled and isinstance(parameters, dict)
            else None
        )
        if converted is None or not isinstance(name, str):
            result.append({**tool, "function": {**function, "strict": False}})
            continue
        result.append(
            {**tool, "function": {**function, "parameters": converted, "strict": True}}
        )
        names.add(name)
    return PreparedTools(result, frozenset(names))
