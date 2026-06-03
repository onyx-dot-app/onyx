"""Expression resolution for flow specs.

There is exactly one syntax: ``{{ path }}``. A path walks plain data that the
run has already produced — there is no evaluation, no function calls and no
way to reach anything the engine did not put in the context. That is a
deliberate limit rather than an unfinished feature: a spec is authored in a
browser and executed on a worker, so anything richer than a lookup would be
remote code execution with extra steps.

Four roots are available:

``trigger``  whatever started the run (a webhook body, a manual payload)
``steps``    completed node outputs, keyed by node id
``item``     the current element while a node fans out over ``for_each``
``index``    that element's 0-based position

Whether an expression yields a native value or a string depends on how it is
written, which is the one piece of cleverness worth remembering:

    "{{ steps.fetch.items }}"          -> the list itself
    "found {{ steps.fetch.total }}"    -> "found 12"

A lone expression keeps its type so ``for_each`` gets a real list and a
condition compares real numbers. Mix it with any other text and you have asked
for a string, so you get one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# `.key`, `[0]`, `[-1]`, `['key-with-dashes']` — enough for real API payloads
# without inviting a grammar.
_STEP_RE = re.compile(
    r"""
      \.(?P<attr>[A-Za-z_][A-Za-z0-9_]*)
    | \[(?P<index>-?\d+)\]
    | \[(?P<quote>['"])(?P<key>[^'"]*)(?P=quote)\]
    """,
    re.VERBOSE,
)
_ROOT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*")

_EXPRESSION_RE = re.compile(r"\{\{(?P<body>.*?)\}\}", re.DOTALL)

# Guards a runaway nested structure in a node's `body` or `fields`.
MAX_STRUCTURE_DEPTH = 20


class ExpressionError(ValueError):
    """An expression that could not be resolved against the run context.

    The message names the path that failed rather than the whole expression,
    because the useful question is always "which hop was missing".
    """


@dataclass
class RunContext:
    """Everything an expression is allowed to see.

    ``steps`` is mutated as the run progresses; the rest is fixed per node
    execution. Passed around by value so a fan-out iteration cannot leak its
    ``item`` into a sibling.
    """

    trigger: Any = None
    steps: dict[str, Any] = field(default_factory=dict)
    item: Any = None
    index: int | None = None

    def roots(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "steps": self.steps,
            "item": self.item,
            "index": self.index,
        }

    def for_item(self, item: Any, index: int) -> RunContext:
        """A copy bound to one element of a fan-out."""
        return RunContext(
            trigger=self.trigger, steps=self.steps, item=item, index=index
        )


def lookup(path: str, context: RunContext) -> Any:
    """Walk ``path`` through the context and return what is there.

    Raises:
        ExpressionError: if the root is unknown or a hop does not exist.
    """
    path = path.strip()
    if not path:
        raise ExpressionError("empty expression")

    root_match = _ROOT_RE.match(path)
    if not root_match:
        raise ExpressionError(f"'{path}' does not start with a name")

    root_name = root_match.group(0)
    roots = context.roots()
    if root_name not in roots:
        raise ExpressionError(
            f"unknown root '{root_name}' — use one of " + ", ".join(sorted(roots))
        )

    current = roots[root_name]
    walked = root_name
    position = root_match.end()

    while position < len(path):
        step = _STEP_RE.match(path, position)
        if not step:
            raise ExpressionError(f"cannot read '{path[position:]}' in '{path}'")
        position = step.end()

        if step.group("attr") is not None:
            current = _read_key(current, step.group("attr"), walked)
            walked = f"{walked}.{step.group('attr')}"
        elif step.group("index") is not None:
            current = _read_index(current, int(step.group("index")), walked)
            walked = f"{walked}[{step.group('index')}]"
        else:
            current = _read_key(current, step.group("key"), walked)
            walked = f"{walked}['{step.group('key')}']"

    return current


def _read_key(value: Any, key: str, walked: str) -> Any:
    if not isinstance(value, dict):
        raise ExpressionError(f"'{walked}' is {_describe(value)}, so it has no '{key}'")
    if key not in value:
        available = ", ".join(sorted(str(k) for k in value)[:8]) or "nothing"
        raise ExpressionError(f"'{walked}' has no '{key}' (it has: {available})")
    return value[key]


def _read_index(value: Any, index: int, walked: str) -> Any:
    if not isinstance(value, list):
        raise ExpressionError(
            f"'{walked}' is {_describe(value)}, so it cannot be indexed"
        )
    if not -len(value) <= index < len(value):
        raise ExpressionError(
            f"'{walked}' has {len(value)} item(s), so [{index}] is out of range"
        )
    return value[index]


def _describe(value: Any) -> str:
    if value is None:
        return "empty"
    return {
        dict: "an object",
        list: "a list",
        str: "text",
        bool: "a true/false value",
        int: "a number",
        float: "a number",
    }.get(type(value), type(value).__name__)


def walk_path(root: Any, path: str, *, root_name: str = "value") -> Any:
    """Walk a dotted path through an arbitrary value.

    Same grammar as an expression body, minus the named roots. Used where a
    node points into a payload it just produced — an HTTP node's
    ``result_path``, for instance — so there is one path syntax to learn
    rather than two.
    """
    path = path.strip()
    if not path:
        return root

    current = root
    walked = root_name
    position = 0
    # A leading dot is optional: `body.items` and `.body.items` both read.
    normalized = path if path.startswith((".", "[")) else f".{path}"

    while position < len(normalized):
        step = _STEP_RE.match(normalized, position)
        if not step:
            raise ExpressionError(f"cannot read '{normalized[position:]}' in '{path}'")
        position = step.end()

        if step.group("attr") is not None:
            current = _read_key(current, step.group("attr"), walked)
            walked = f"{walked}.{step.group('attr')}"
        elif step.group("index") is not None:
            current = _read_index(current, int(step.group("index")), walked)
            walked = f"{walked}[{step.group('index')}]"
        else:
            current = _read_key(current, step.group("key"), walked)
            walked = f"{walked}['{step.group('key')}']"

    return current


def resolve(template: str, context: RunContext) -> Any:
    """Resolve a spec string, keeping the native type when it is a lone
    expression and interpolating otherwise."""
    if not isinstance(template, str):
        return template

    lone = _lone_expression(template)
    if lone is not None:
        return lookup(lone, context)
    return render_text(template, context)


def _lone_expression(template: str) -> str | None:
    """The body of ``template`` when it is a single expression and nothing else.

    Checked by scanning rather than by anchoring a regex to both ends: an
    end-anchored pattern happily stretches one match across
    ``"{{ a }}{{ b }}"`` and reads the ``}}{{`` in the middle as part of the
    path.
    """
    stripped = template.strip()
    matches = list(_EXPRESSION_RE.finditer(stripped))
    if len(matches) == 1 and matches[0].span() == (0, len(stripped)):
        return matches[0].group("body")
    return None


def render_text(template: str, context: RunContext) -> str:
    """Resolve every expression in ``template`` and return a string."""
    if not isinstance(template, str):
        return _stringify(template)

    def substitute(match: re.Match[str]) -> str:
        return _stringify(lookup(match.group("body"), context))

    return _EXPRESSION_RE.sub(substitute, template)


def resolve_structure(value: Any, context: RunContext, _depth: int = 0) -> Any:
    """Resolve expressions anywhere inside a nested structure.

    Used for a request body, where the author may have written expressions in
    keys as well as values.
    """
    if _depth > MAX_STRUCTURE_DEPTH:
        raise ExpressionError(
            f"structure nests deeper than {MAX_STRUCTURE_DEPTH} levels"
        )
    if isinstance(value, str):
        return resolve(value, context)
    if isinstance(value, dict):
        return {
            render_text(key, context): resolve_structure(item, context, _depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [resolve_structure(item, context, _depth + 1) for item in value]
    return value


def _stringify(value: Any) -> str:
    """Render a value for interpolation into text.

    JSON spelling for booleans and containers, because these strings mostly
    end up in URLs, headers and prompts where `True` and `{'a': 1}` would be
    wrong or at least surprising.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def referenced_node_ids(value: Any) -> set[str]:
    """Node ids a spec fragment reads through ``steps.*``.

    Used by the editor to warn about a node reading something that cannot have
    run yet. Best effort by design: a malformed expression is the validator's
    problem, not this function's.
    """
    found: set[str] = set()
    _collect_step_refs(value, found)
    return found


def _collect_step_refs(value: Any, found: set[str]) -> None:
    if isinstance(value, str):
        for match in _EXPRESSION_RE.finditer(value):
            body = match.group("body").strip()
            if not body.startswith("steps"):
                continue
            step = _STEP_RE.match(body, len("steps"))
            if step and step.group("attr"):
                found.add(step.group("attr"))
    elif isinstance(value, dict):
        for key, item in value.items():
            _collect_step_refs(key, found)
            _collect_step_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_step_refs(item, found)
