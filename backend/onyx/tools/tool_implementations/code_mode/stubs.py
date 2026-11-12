"""Python stubs that expose Onyx tools to code mode programs as async functions."""

import builtins
import json
import keyword
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from types import UnionType
from typing import Literal, Union, get_args, get_origin

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
    SchemaType,
    SearchableFunction,
    StubParameter,
    StubResultType,
)
from onyx.tools.tool_implementations.code_mode.sandbox import (
    PRELUDE_STUBS,
    SANDBOX_NAMES,
    YIELD_CONTROL_STUB,
    HostFunction,
)
from onyx.tools.tool_implementations.code_mode.store import (
    STORE_FUNCTIONS,
    STORE_STUBS,
    JsonCopy,
    json_value,
)
from onyx.tools.tool_implementations.code_mode.tool_search import (
    TOOL_SEARCH_FUNCTION,
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
_NAME = re.compile(r"\w+")
# Argument and field names can be soft keywords such as `type`; only hard
# keywords are invalid there.
_KEYWORDS: frozenset[str] = frozenset(keyword.kwlist)
# Names a tool function must not shadow: Python keywords, builtins, the names
# the sandbox, the store and the tool search give programs, and the typing names
# of the stub header. The result types that the tools declare are added per stub
# module.
_RESERVED_FUNCTION_NAMES: frozenset[str] = frozenset(
    {
        *keyword.kwlist,
        *keyword.softkwlist,
        *dir(builtins),
        *_TYPING_NAMES,
        *SANDBOX_NAMES,
        *STORE_FUNCTIONS,
        *TOOL_SEARCH_NAMES,
    }
)


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
    # The imports, store()/load(), yield_control() and, with deferred
    # functions, tool_search() of every stub module.
    header: str
    # The stub module that the `execute_code` description lists: no deferred
    # functions.
    listed_text: str
    # tool_search() over the deferred functions; None when there are none.
    tool_index: ToolIndex | None

    def program_text(self, code: str) -> str:
        """The stub module that types one program: the listed functions, the
        deferred functions whose names `code` uses, and the names of the
        modules that every program imports.

        So the module does not grow with the deferred functions that a
        program does not name. Every function stays callable; one that the
        code reaches without its name runs without types.
        """
        # Python reads identifiers in NFKC form.
        names = set(_NAME.findall(unicodedata.normalize("NFKC", code)))
        return _module(
            f"{self.header}\n\n\n{PRELUDE_STUBS}",
            (
                function
                for name, function in self.functions.items()
                if not function.deferred or name in names
            ),
        )

    @property
    def async_functions(self) -> dict[str, HostFunction]:
        """Host functions that only some programs have; programs await them."""
        if self.tool_index is None:
            return {}
        return {TOOL_SEARCH_FUNCTION: self.tool_index.tool_search}

    @property
    def deferred_namespaces(self) -> list[str]:
        """The namespaces of the deferred functions, in name order."""
        return sorted(
            {
                namespace
                for function in self.functions.values()
                if function.deferred
                and (namespace := function.tool.code_mode_function_name.namespace)
            }
        )

    @property
    def has_deferred_functions_without_namespace(self) -> bool:
        return any(
            function.deferred
            and function.tool.code_mode_function_name.namespace is None
            for function in self.functions.values()
        )


def python_identifier(
    name: str, *, fallback: str, reserved: frozenset[str], suffix: str
) -> str:
    """Map a name to a Python identifier; `suffix` is appended to reserved names."""
    # Python reads identifiers in NFKC form, so a program's keyword names arrive
    # normalized; keep only characters that are valid in that form.
    normalized = unicodedata.normalize("NFKC", name.strip())
    identifier = (
        "".join(char if f"_{char}".isidentifier() else "_" for char in normalized)
        or fallback
    )
    if not identifier.isidentifier():
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
    return python_identifier(argument, fallback="arg", reserved=_KEYWORDS, suffix="_")


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


_UNKNOWN = SchemaType(annotation=ANY, nullable=False)


def schema_type(
    schema: JsonValue,
    root: Mapping[str, JsonValue],
    *,
    budget: SchemaRefBudget | None = None,
    ref_path: tuple[str, ...] = (),
    depth: int = 0,
) -> SchemaType:
    """Render a JSON Schema as a Python type annotation and whether it accepts
    null; unknown shapes become Any. `$ref` chains end at MAX_SCHEMA_DEPTH and
    the reference bounds, as Any that is not known to accept null."""
    budget = budget if budget is not None else SchemaRefBudget()
    if not isinstance(schema, dict) or depth > MAX_SCHEMA_DEPTH:
        return _UNKNOWN

    def render(sub: JsonValue, path: tuple[str, ...] = ref_path) -> SchemaType:
        return schema_type(sub, root, budget=budget, ref_path=path, depth=depth + 1)

    ref = schema.get("$ref")
    if isinstance(ref, str):
        if (
            ref_path.count(ref) >= MAX_REF_EXPANSIONS_PER_PATH
            or budget.total >= MAX_REF_EXPANSIONS_TOTAL
        ):
            return _UNKNOWN
        target = _resolve_ref(ref, root)
        if target is None:
            return _UNKNOWN
        budget.total += 1
        return render(target, (*ref_path, ref))

    explicit_null = schema.get("nullable") is True

    def typed(annotation: str, nullable: bool = False) -> SchemaType:
        nullable = nullable or explicit_null
        return SchemaType(
            annotation=_union([annotation, "None"]) if nullable else annotation,
            nullable=nullable,
        )

    def union(members: Sequence[SchemaType]) -> SchemaType:
        return typed(
            _union([member.annotation for member in members] or [ANY]),
            any(member.nullable for member in members),
        )

    if "const" in schema:
        return typed(_literal([schema["const"]]) or ANY, schema["const"] is None)

    enum = schema.get("enum")
    if isinstance(enum, list):
        return typed(_literal(enum) or ANY, None in enum)

    for combinator in ("anyOf", "oneOf"):
        options = schema.get(combinator)
        if isinstance(options, list) and options:
            return union([render(option) for option in options])

    all_of = schema.get("allOf")
    if isinstance(all_of, list) and all_of:
        # Intersections have no Python spelling; one member renders exactly.
        return union([render(all_of[0])]) if len(all_of) == 1 else typed(ANY)

    kind = schema.get("type")
    if isinstance(kind, list):
        return union([render({**schema, "type": item}) for item in kind])
    if kind is None:
        kind = (
            "object"
            if "properties" in schema
            else "array"
            if "items" in schema
            else None
        )
    if not isinstance(kind, str):
        return typed(ANY)

    if kind in _PRIMITIVES:
        return typed(_PRIMITIVES[kind], kind == "null")
    if kind == "array":
        items = schema.get("items")
        return typed(f"list[{render(items).annotation if items is not None else ANY}]")
    if kind == "object":
        additional = schema.get("additionalProperties")
        if not schema.get("properties") and isinstance(additional, dict):
            return typed(f"dict[str, {render(additional).annotation}]")
        return typed("dict[str, Any]")
    return typed(ANY)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split()) if "\n" not in text else text.strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


# Characters to write as escapes: control characters other than tab and newline
# (NUL is a parse error; a carriage return reads as a newline), and lone
# surrogates, which have no UTF-8 encoding.
_UNWRITABLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]")


def _escape_unwritable(match: re.Match[str]) -> str:
    code = ord(match.group())
    return f"\\x{code:02x}" if code <= 0xFF else f"\\u{code:04x}"


def _docstring_text(text: str) -> str:
    """`text` escaped to sit between triple quotes: backslashes, characters that
    source text cannot hold, and each quote that starts a run of three or ends
    the text."""
    escaped = _UNWRITABLE.sub(_escape_unwritable, text.replace("\\", "\\\\"))
    return re.sub(r'"(?=""|\Z)', r'\\"', escaped)


def _object_keys_summary(schema: JsonValue) -> str:
    if not isinstance(schema, dict):
        return ""
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return ""
    required_names = _required_names(schema)
    keys = [
        f"{name}{'' if name in required_names else '?'}" for name in sorted(properties)
    ]
    return f" Keys: {', '.join(keys)}."


def _required_names(schema: Mapping[str, JsonValue]) -> set[str]:
    """The property names that `schema` requires; entries that are not str are
    ignored."""
    required = schema.get("required")
    if not isinstance(required, list):
        return set()
    return {name for name in required if isinstance(name, str)}


def _parameters(
    parameters: Mapping[str, JsonValue], *, typed: bool
) -> tuple[list[StubParameter], dict[str, str], str | None]:
    """The named arguments, their Python names mapped to the tool's names, and
    the annotation of the other keyword arguments that the schema admits
    through `additionalProperties`, or None when it admits none."""
    budget = SchemaRefBudget()
    additional = parameters.get("additionalProperties")
    extra = (
        (
            schema_type(additional, parameters, budget=budget).annotation
            if typed
            else ANY
        )
        if additional is True or isinstance(additional, dict)
        else None
    )
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return [], {}, extra
    # OpenAPI-derived schemas omit `required`; every argument is then optional.
    required = _required_names(parameters)
    names = unique_identifiers(properties, str, argument_name)
    result: list[StubParameter] = []
    for python_name, original in names.items():
        prop = properties[original]
        rendered = schema_type(prop, parameters, budget=budget)
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
                annotation=rendered.annotation if typed else ANY,
                required=original in required,
                # Strict schemas list optional arguments as required and nullable.
                nullable=rendered.nullable,
                description=_clip(description, MAX_ARGUMENT_DESCRIPTION_CHARS),
            )
        )
    # Arguments without a default first, each group in name order.
    result.sort(key=lambda parameter: (parameter.has_default, parameter.python_name))
    return result, names, extra


def _render_function(
    function_name: str,
    description: str,
    parameters: Sequence[StubParameter],
    result_annotation: str,
    *,
    tool_name: str,
    returns: str | None = None,
    usage: str | None = None,
    extra: str | None = None,
) -> str:
    """`extra` annotates the keyword arguments beyond `parameters`; None admits
    none."""
    rendered = [
        f"{p.python_name}: {_union([p.annotation, 'None'])} = None"
        if p.has_default
        else f"{p.python_name}: {p.annotation}"
        for p in parameters
    ]
    if rendered:
        rendered.insert(0, "*")
    if extra is not None:
        taken = {p.python_name for p in parameters}
        kwargs_name = "kwargs"
        while kwargs_name in taken:
            kwargs_name += "_"
        rendered.append(f"**{kwargs_name}: {extra}")
    signature = ", ".join(rendered)
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


def _python_type(annotation: object, nested: list[type[BaseModel]]) -> str:
    """A field's type as a stub annotation; models it names are added to `nested`."""
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        nested.append(annotation)
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
    pending = [model]
    rendered: dict[type[BaseModel], str] = {}
    while pending:
        current = pending.pop()
        if current in rendered:
            continue
        nested: list[type[BaseModel]] = []
        lines = [f"class {current.__name__}(TypedDict):"]
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
        rendered[current] = "\n".join(lines)
        pending.extend(nested)
    return sorted(rendered.values())


def _model_result_type(spec: CodeModeResultSpec) -> StubResultType:
    return StubResultType(
        annotation=spec.type_annotation,
        declarations=tuple(model_declarations(spec.model)) if spec.model else (),
    )


def _type_name(function_name: str, taken: set[str]) -> str:
    """A unique result type name for a function, such as `ListTicketsResult`."""
    base = "".join(part[:1].upper() + part[1:] for part in function_name.split("_"))
    if not base.isidentifier():
        # Parts after leading underscores can start with a digit.
        base = f"Tool{base}"
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
        # Python reads a field name in NFKC form, so a name that NFKC changes
        # would not match its JSON key.
        or any(
            not name.isidentifier()
            or unicodedata.normalize("NFKC", name) != name
            or name in _KEYWORDS
            for name in properties
        )
    ):
        return StubResultType(
            annotation=schema_type(schema, schema).annotation, declarations=()
        )
    required = _required_names(schema)
    type_name = _type_name(function_name, taken)
    budget = SchemaRefBudget()
    fields = []
    for name, prop in properties.items():
        annotation = schema_type(prop, schema, budget=budget).annotation
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
        parameters, names, extra = _parameters(definition.parameters, typed=typed)
        stub = _render_function(
            function_name,
            description,
            [] if open_signature else parameters,
            result.annotation,
            tool_name=tool.name,
            returns=spec.returns,
            usage=spec.usage,
            extra=ANY if open_signature else extra,
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
    declarations: dict[str, str] = {}
    for result_type in model_types.values():
        for declaration in result_type.declarations:
            for name in _DECLARED_TYPE.findall(declaration):
                if declarations.setdefault(name, declaration) != declaration:
                    raise ValueError(
                        f"Two result models are named {name}; the stub module "
                        "declares one TypedDict per name."
                    )
    declared_types = frozenset(declarations)
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
        header=header,
        listed_text=_module(
            header,
            (function for function in functions.values() if not function.deferred),
        ),
        tool_index=ToolIndex([_searchable(function) for function in deferred])
        if deferred
        else None,
    )


def tool_arguments(function: ToolFunction, kwargs: Mapping[str, object]) -> JsonCopy:
    """Convert program keyword arguments to tool arguments, as a JSON copy.

    None is sent for arguments that accept null and left out for others; a
    required argument that accepts null is sent as null when it is left out.
    Raises TypeError when a value is not JSON data and ValueError past
    MAX_TOOL_ARGUMENT_BYTES.
    """
    nullable = function.nullable_arguments
    arguments: dict[str, object] = {
        function.argument_names.get(key, key): value
        for key, value in kwargs.items()
        if value is not None or key in nullable
    }
    for key in function.required_arguments & nullable:
        arguments.setdefault(function.argument_names.get(key, key), None)
    # One copy for all arguments: they can share one large value.
    return json_value(
        arguments,
        f"The argument dict of {function.function_name}()",
        MAX_TOOL_ARGUMENT_BYTES,
    )


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
