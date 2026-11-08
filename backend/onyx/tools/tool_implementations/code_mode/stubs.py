"""Python stubs that expose Onyx tools to code mode programs as async functions."""

import builtins
import json
import keyword
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from types import UnionType
from typing import Literal, Union, cast, get_args, get_origin

from pydantic import BaseModel, ConfigDict, JsonValue

from onyx.llm.models import ToolResult
from onyx.tools.interface import Tool
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeResultKind,
    CodeModeResultSpec,
    CustomToolCallSummary,
)
from onyx.tools.tool_implementations.code_mode.models import (
    SchemaRefBudget,
    SearchableFunction,
    StubParameter,
    StubResultType,
)
from onyx.tools.tool_implementations.code_mode.sandbox import (
    SANDBOX_NAMES,
    YIELD_CONTROL_STUB,
)
from onyx.tools.tool_implementations.code_mode.store import (
    STORE_FUNCTIONS,
    STORE_STUBS,
    json_value,
)
from onyx.tools.tool_implementations.code_mode.tool_search import (
    TOOL_SEARCH_NAMES,
    TOOL_SEARCH_STUBS,
    ToolIndex,
)

# Bounds on each rendered function, so one tool with a large schema cannot fill
# the tool description that the model reads on every step.
MAX_STUB_CHARS = 16_000
MAX_TOOL_DESCRIPTION_CHARS = 2_000
MAX_ARGUMENT_DESCRIPTION_CHARS = 400
MAX_REF_EXPANSIONS_PER_PATH = 2
MAX_REF_EXPANSIONS_TOTAL = 32
MAX_SCHEMA_DEPTH = 8
# JSON bytes of the arguments of one tool call; the host keeps them for the
# call's life.
MAX_TOOL_ARGUMENT_BYTES = 256 * 1024

ANY = "Any"


_TYPING_NAMES = ("Any", "Literal", "NotRequired", "TypedDict")
_STUB_HEADER = (
    f"from typing import {', '.join(_TYPING_NAMES)}\n\n\n{STORE_STUBS}\n\n\n"
    f"{YIELD_CONTROL_STUB}"
)

_DECLARED_TYPE = re.compile(r"^class (\w+)", re.MULTILINE)
_SYNTAX_NAMES: frozenset[str] = frozenset({*keyword.kwlist, *keyword.softkwlist})
# Names a tool function must not shadow: Python syntax, builtins, the names
# the sandbox, the store and the tool search give programs, and the typing names
# of the stub header. The result types that the tools declare are added per stub
# module.
_RESERVED_FUNCTION_NAMES: frozenset[str] = frozenset(
    {
        *_SYNTAX_NAMES,
        *dir(builtins),
        *_TYPING_NAMES,
        *SANDBOX_NAMES,
        *STORE_FUNCTIONS,
        *TOOL_SEARCH_NAMES,
    }
)

_IDENTIFIER_INVALID = re.compile(r"\W")


class ToolFunction(BaseModel):
    """One tool as a Python function inside the sandbox. It stays here, not in
    models.py: `Tool` imports lead back to models.py."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    function_name: str
    tool: Tool
    result: CodeModeResultSpec
    # Python keyword name -> tool argument name.
    argument_names: Mapping[str, str]
    # Python names of the arguments that the schema requires, and of those that
    # accept null.
    required_arguments: frozenset[str]
    nullable_arguments: frozenset[str]
    description: str
    stub: str
    # Declarations of the types that the stub names.
    declarations: tuple[str, ...]

    @property
    def deferred(self) -> bool:
        return self.tool.code_mode_exposure is CodeModeExposure.DEFERRED


class ToolStubs(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    functions: Mapping[str, ToolFunction]
    # Complete stub module that the type checker reads: every function.
    text: str
    # The stub module that the `execute_code` description lists: no deferred
    # functions.
    listed_text: str
    # tool_search() over the deferred functions; None when there are none.
    tool_index: ToolIndex | None


def python_identifier(
    name: str, *, fallback: str, reserved: frozenset[str], suffix: str
) -> str:
    """Map a name to a Python identifier; `suffix` is appended to reserved names."""
    identifier = _IDENTIFIER_INVALID.sub("_", name.strip()) or fallback
    if identifier[0].isdigit():
        identifier = f"{fallback}_{identifier}"
    return f"{identifier}{suffix}" if identifier in reserved else identifier


def function_name(tool_name: str, declared_types: frozenset[str] = frozenset()) -> str:
    """`declared_types` are the result type names in the same stub module."""
    return python_identifier(
        tool_name,
        fallback="tool",
        reserved=_RESERVED_FUNCTION_NAMES | declared_types,
        suffix="_tool",
    )


def argument_name(argument: str) -> str:
    return python_identifier(
        argument, fallback="arg", reserved=_SYNTAX_NAMES, suffix="_"
    )


def unique_identifiers[T](
    items: Iterable[T], name: Callable[[T], str], identifier: Callable[[str], str]
) -> dict[str, T]:
    """Give each item a unique identifier, deterministically: in name order, a
    repeated identifier gets the suffix _2, _3, and so on."""
    assigned: dict[str, T] = {}
    for item in sorted(items, key=name):
        base = identifier(name(item))
        candidate = base
        number = 2
        while candidate in assigned:
            candidate = f"{base}_{number}"
            number += 1
        assigned[candidate] = item
    return dict(sorted(assigned.items()))


def _resolve_ref(ref: str, root: Mapping[str, JsonValue]) -> JsonValue | None:
    if not ref.startswith("#/"):
        return None
    node: JsonValue = dict(root)
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _literal(values: Sequence[JsonValue]) -> str | None:
    rendered: list[str] = []
    for value in values:
        if value is None:
            rendered.append("None")
        elif isinstance(value, (bool, int, str)):
            rendered.append(repr(value))
        else:
            return None
    if not rendered:
        return None
    literals = [item for item in rendered if item != "None"]
    parts = [f"Literal[{', '.join(literals)}]"] if literals else []
    if "None" in rendered:
        parts.append("None")
    return " | ".join(parts)


def _union(types: Sequence[str]) -> str:
    unique: list[str] = []
    for item in types:
        for part in _split_union(item):
            if part not in unique:
                unique.append(part)
    if ANY in unique:
        return ANY
    # None last reads naturally: `str | None`.
    unique.sort(key=lambda part: part == "None")
    return " | ".join(unique)


def _split_union(annotation: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(annotation):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "|" and depth == 0:
            parts.append(annotation[start:index].strip())
            start = index + 1
    parts.append(annotation[start:].strip())
    return [part for part in parts if part]


_PRIMITIVES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "null": "None",
}


def schema_annotation(
    schema: JsonValue,
    root: Mapping[str, JsonValue],
    *,
    budget: SchemaRefBudget | None = None,
    ref_path: tuple[str, ...] = (),
    depth: int = 0,
) -> str:
    """Render a JSON Schema as a Python type annotation; unknown shapes become Any."""
    budget = budget if budget is not None else SchemaRefBudget()
    if not isinstance(schema, dict) or depth > MAX_SCHEMA_DEPTH:
        return ANY

    def render(sub: JsonValue, path: tuple[str, ...] = ref_path) -> str:
        return schema_annotation(
            sub, root, budget=budget, ref_path=path, depth=depth + 1
        )

    ref = schema.get("$ref")
    if isinstance(ref, str):
        if (
            ref_path.count(ref) >= MAX_REF_EXPANSIONS_PER_PATH
            or budget.total >= MAX_REF_EXPANSIONS_TOTAL
        ):
            return ANY
        target = _resolve_ref(ref, root)
        if target is None:
            return ANY
        budget.total += 1
        return render(target, (*ref_path, ref))

    nullable = schema.get("nullable") is True

    def with_null(annotation: str) -> str:
        return _union([annotation, "None"]) if nullable else annotation

    if "const" in schema:
        literal = _literal([schema["const"]])
        return with_null(literal) if literal else ANY

    enum = schema.get("enum")
    if isinstance(enum, list):
        literal = _literal(enum)
        return with_null(literal) if literal else ANY

    for combinator in ("anyOf", "oneOf"):
        options = schema.get(combinator)
        if isinstance(options, list) and options:
            return with_null(_union([render(option) for option in options]))

    all_of = schema.get("allOf")
    if isinstance(all_of, list) and all_of:
        # Intersections have no Python spelling; one member renders exactly.
        return with_null(render(all_of[0])) if len(all_of) == 1 else ANY

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return with_null(
            _union([render({**schema, "type": item}) for item in schema_type] or [ANY])
        )
    if schema_type is None:
        schema_type = (
            "object"
            if "properties" in schema
            else "array"
            if "items" in schema
            else None
        )
    if not isinstance(schema_type, str):
        return ANY

    if schema_type in _PRIMITIVES:
        return with_null(_PRIMITIVES[schema_type])
    if schema_type == "array":
        items = schema.get("items")
        return with_null(f"list[{render(items) if items is not None else ANY}]")
    if schema_type == "object":
        additional = schema.get("additionalProperties")
        if not schema.get("properties") and isinstance(additional, dict):
            return with_null(f"dict[str, {render(additional)}]")
        return with_null("dict[str, Any]")
    return ANY


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split()) if "\n" not in text else text.strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _docstring_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def _object_keys_summary(schema: JsonValue) -> str:
    if not isinstance(schema, dict):
        return ""
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return ""
    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    keys = [
        f"{name}{'' if name in required_names else '?'}" for name in sorted(properties)
    ]
    return f" Keys: {', '.join(keys)}."


def _admits_null(schema: JsonValue) -> bool:
    """Whether a JSON schema accepts null."""
    if not isinstance(schema, dict):
        return False
    if schema.get("nullable") is True or schema.get("type") == "null":
        return True
    types = schema.get("type")
    if isinstance(types, list) and "null" in types:
        return True
    return any(
        isinstance(options, list) and any(_admits_null(option) for option in options)
        for options in (schema.get("anyOf"), schema.get("oneOf"))
    )


def _parameters(
    parameters: Mapping[str, JsonValue], *, typed: bool
) -> tuple[list[StubParameter], dict[str, str]]:
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return [], {}
    required_field = parameters.get("required")
    # OpenAPI-derived schemas omit `required`; every argument is then optional.
    required = (
        {name for name in required_field if isinstance(name, str)}
        if isinstance(required_field, list)
        else set()
    )
    names = unique_identifiers(properties, str, argument_name)
    budget = SchemaRefBudget()
    result: list[StubParameter] = []
    for python_name, original in names.items():
        prop = properties[original]
        annotation = (
            schema_annotation(prop, parameters, budget=budget) if typed else ANY
        )
        description = ""
        if isinstance(prop, dict):
            raw = prop.get("description")
            description = raw if isinstance(raw, str) else ""
            description += _object_keys_summary(prop)
        if python_name != original:
            description = f"(tool argument `{original}`) {description}".strip()
        result.append(
            StubParameter(
                python_name=python_name,
                annotation=annotation,
                required=original in required,
                # Strict schemas list optional arguments as required and nullable.
                nullable=_admits_null(prop),
                description=_clip(description, MAX_ARGUMENT_DESCRIPTION_CHARS),
            )
        )
    # Arguments without a default first, each group in name order.
    result.sort(key=lambda parameter: (parameter.has_default, parameter.python_name))
    return result, names


def _render_function(
    function_name: str,
    description: str,
    parameters: Sequence[StubParameter],
    result_annotation: str,
    *,
    tool_name: str,
    returns: str | None = None,
    usage: str | None = None,
    open_signature: bool = False,
) -> str:
    if open_signature:
        signature = "**kwargs: Any"
    elif parameters:
        rendered = [
            f"{p.python_name}: {_union([p.annotation, 'None'])} = None"
            if p.has_default
            else f"{p.python_name}: {p.annotation}"
            for p in parameters
        ]
        signature = "*, " + ", ".join(rendered)
    else:
        signature = ""
    doc_lines = [description or "No description."]
    if tool_name != function_name:
        doc_lines.append(f"Tool name: {tool_name}")
    if usage:
        doc_lines.extend(["", usage])
    documented = [p for p in parameters if p.description]
    if documented:
        doc_lines.append("")
        doc_lines.append("Args:")
        doc_lines.extend(f"    {p.python_name}: {p.description}" for p in documented)
    if returns:
        doc_lines.extend(["", "Returns:", f"    {returns}"])
    # Escaped once here, so no part can end the docstring.
    body = "\n".join(
        f"    {_docstring_text(line)}" if line else "" for line in doc_lines
    )
    return (
        f"async def {function_name}({signature}) -> {result_annotation}:\n"
        f'    """\n{body}\n    """\n'
        "    ..."
    )


_SCALAR_TYPES: dict[type, str] = {str: "str", int: "int", float: "float", bool: "bool"}


def _python_type(annotation: object, nested: dict[str, type[BaseModel]]) -> str:
    """A field's type as a stub annotation; models it names are added to `nested`."""
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        nested[annotation.__name__] = annotation
        return annotation.__name__
    if isinstance(annotation, type) and annotation in _SCALAR_TYPES:
        return _SCALAR_TYPES[annotation]
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is list and arguments:
        return f"list[{_python_type(arguments[0], nested)}]"
    if origin is dict and len(arguments) == 2:
        return (
            f"dict[{_python_type(arguments[0], nested)}, "
            f"{_python_type(arguments[1], nested)}]"
        )
    if origin is Literal:
        return f"Literal[{', '.join(repr(argument) for argument in arguments)}]"
    if origin in (Union, UnionType):
        return _union([_python_type(argument, nested) for argument in arguments])
    return ANY


def model_declarations(model: type[BaseModel]) -> list[str]:
    """TypedDict declarations of a model and of the models its fields name, as
    the model's JSON has them.

    A field with `exclude_if` is left out of the JSON when it is None, so it is
    `NotRequired` and its type has no None. A field description becomes the
    field's docstring.
    """
    pending = {model.__name__: model}
    rendered: dict[str, str] = {}
    while pending:
        name, current = pending.popitem()
        if name in rendered:
            continue
        nested: dict[str, type[BaseModel]] = {}
        lines = [f"class {name}(TypedDict):"]
        for field, info in current.model_fields.items():
            annotation = _python_type(info.annotation, nested)
            if info.exclude_if is not None:
                value = _union(
                    [part for part in _split_union(annotation) if part != "None"]
                )
                annotation = f"NotRequired[{value}]"
            lines.append(f"    {field}: {annotation}")
            if info.description:
                lines.append(f'    """{_docstring_text(info.description)}"""')
        rendered[name] = "\n".join(lines)
        pending.update(nested)
    return [rendered[name] for name in sorted(rendered)]


def _model_result_type(spec: CodeModeResultSpec) -> StubResultType:
    return StubResultType(
        annotation=spec.type_annotation,
        declarations=tuple(model_declarations(spec.model)) if spec.model else (),
    )


def _type_name(function_name: str, taken: set[str]) -> str:
    """A unique result type name for a function, such as `ListTicketsResult`."""
    base = "".join(part[:1].upper() + part[1:] for part in function_name.split("_"))
    candidate = f"{base}Result"
    number = 2
    while candidate in taken:
        candidate = f"{base}Result{number}"
        number += 1
    taken.add(candidate)
    return candidate


def _schema_result_type(
    function_name: str, schema: dict[str, JsonValue], taken: set[str]
) -> StubResultType:
    """The result type that a JSON Schema describes. A top-level object is a
    TypedDict; its nested objects stay `dict[str, Any]`."""
    properties = schema.get("properties")
    if (
        schema.get("type", "object") != "object"
        or not isinstance(properties, dict)
        or not properties
        or any(not name.isidentifier() or name in _SYNTAX_NAMES for name in properties)
    ):
        return StubResultType(
            annotation=schema_annotation(schema, schema), declarations=()
        )
    required_field = schema.get("required")
    required = set(required_field) if isinstance(required_field, list) else set()
    type_name = _type_name(function_name, taken)
    budget = SchemaRefBudget()
    fields = []
    for name, prop in properties.items():
        annotation = schema_annotation(prop, schema, budget=budget)
        fields.append(
            f"    {name}: {annotation if name in required else f'NotRequired[{annotation}]'}"
        )
    return StubResultType(
        annotation=type_name,
        declarations=("\n".join([f"class {type_name}(TypedDict):", *fields]),),
    )


def tool_function(
    function_name: str, tool: Tool, result_type: StubResultType
) -> ToolFunction:
    """Render one tool's stub and result declarations within MAX_STUB_CHARS.

    Past the limit the result becomes Any, then the arguments, and last the
    signature takes any keyword arguments.
    """
    definition = tool.tool_definition()
    description = _clip(
        definition.description or tool.description, MAX_TOOL_DESCRIPTION_CHARS
    )
    spec = tool.code_mode_result
    any_result = StubResultType(annotation=ANY, declarations=())
    stub = ""
    names: dict[str, str] = {}
    parameters: list[StubParameter] = []
    for typed, open_signature, result in (
        (True, False, result_type),
        (True, False, any_result),
        (False, False, any_result),
        (False, True, any_result),
    ):
        parameters, names = _parameters(definition.parameters, typed=typed)
        stub = _render_function(
            function_name,
            description,
            [] if open_signature else parameters,
            result.annotation,
            tool_name=tool.name,
            returns=spec.returns,
            usage=spec.usage,
            open_signature=open_signature,
        )
        if len(stub) + sum(len(text) for text in result.declarations) <= MAX_STUB_CHARS:
            break
    return ToolFunction(
        function_name=function_name,
        tool=tool,
        result=spec,
        argument_names=names,
        required_arguments=frozenset(p.python_name for p in parameters if p.required),
        nullable_arguments=frozenset(p.python_name for p in parameters if p.nullable),
        description=description,
        stub=stub,
        declarations=result.declarations,
    )


def _searchable(function: ToolFunction) -> SearchableFunction:
    namespace = function.tool.code_mode_function_name.namespace or ""
    stub = "\n\n\n".join([*function.declarations, function.stub])
    return SearchableFunction(
        name=function.function_name,
        description=function.description,
        stub=stub,
        # The name counts twice, so a match on it ranks above a match in prose.
        text=f"{function.function_name} {function.function_name} {namespace} "
        f"{function.description}",
    )


def _module(header: str, functions: Iterable[ToolFunction]) -> str:
    listed = list(functions)
    declarations = sorted(
        {declaration for function in listed for declaration in function.declarations}
    )
    blocks = [header, *declarations, *(function.stub for function in listed)]
    return "\n\n\n".join(blocks) + "\n"


def build_tool_stubs(tools: Sequence[Tool]) -> ToolStubs:
    """Build the function map and the stub modules for a set of tools."""
    model_types = {
        id(tool): _model_result_type(tool.code_mode_result) for tool in tools
    }
    declared_types = frozenset(
        name
        for result_type in model_types.values()
        for declaration in result_type.declarations
        for name in _DECLARED_TYPE.findall(declaration)
    )
    named = unique_identifiers(
        tools,
        lambda tool: tool.code_mode_function_name.qualified,
        lambda name: function_name(name, declared_types),
    )
    taken = {*declared_types, *named, *_RESERVED_FUNCTION_NAMES}
    functions: dict[str, ToolFunction] = {}
    for name, tool in named.items():
        schema = tool.code_mode_result.output_schema
        functions[name] = tool_function(
            name,
            tool,
            _schema_result_type(name, schema, taken)
            if schema is not None
            else model_types[id(tool)],
        )
    deferred = [function for function in functions.values() if function.deferred]
    header = f"{_STUB_HEADER}\n\n\n{TOOL_SEARCH_STUBS}" if deferred else _STUB_HEADER
    return ToolStubs(
        functions=functions,
        text=_module(header, functions.values()),
        listed_text=_module(
            header,
            (function for function in functions.values() if not function.deferred),
        ),
        tool_index=ToolIndex([_searchable(function) for function in deferred])
        if deferred
        else None,
    )


def tool_arguments(
    function: ToolFunction, kwargs: Mapping[str, object]
) -> dict[str, JsonValue]:
    """Convert program keyword arguments to tool arguments.

    None is sent for arguments that accept null and left out for others; a
    required argument that accepts null is sent as null when it is left out.
    Raises TypeError when a value is not JSON data and ValueError past
    MAX_TOOL_ARGUMENT_BYTES.
    """
    # One copy for all arguments: they can share one large value.
    copied = cast(
        dict[str, JsonValue],
        json_value(
            dict(kwargs),
            f"The argument dict of {function.function_name}()",
            MAX_TOOL_ARGUMENT_BYTES,
        ),
    )
    nullable = function.nullable_arguments
    arguments: dict[str, JsonValue] = {
        function.argument_names.get(key, key): value
        for key, value in copied.items()
        if value is not None or key in nullable
    }
    for key in function.required_arguments & nullable:
        arguments.setdefault(function.argument_names.get(key, key), None)
    return arguments


def program_value(function: ToolFunction, result: ToolResult) -> object:
    """The value a program receives for a tool result; raises RuntimeError for errors."""
    kind = function.result.kind
    if kind is CodeModeResultKind.TEXT and not result.is_error:
        return result.content
    try:
        value: object = json.loads(result.content)
        parsed = True
    except ValueError:
        value, parsed = result.content, False
    if result.is_error:
        # A `{"error": text}` object raises its text.
        error = value.get("error") if isinstance(value, dict) else None
        raise RuntimeError(
            (error if isinstance(error, str) else result.content)
            or f"{function.function_name} failed"
        )
    if kind is CodeModeResultKind.JSON_OBJECT and not (
        parsed and isinstance(value, dict)
    ):
        raise RuntimeError(result.content)
    if (
        isinstance(result.details, CustomToolCallSummary)
        and result.details.structured_result is not None
    ):
        return result.details.structured_result
    if kind is CodeModeResultKind.MCP and isinstance(value, dict):
        return value.get("tool_result", value)
    return value
