#!/usr/bin/env python3
"""Ratchet fixed sleeps and skips without reasons in test code."""

import argparse
import ast
import io
import re
import tokenize
from collections.abc import Iterator
from pathlib import Path
from string import Formatter
from typing import Literal

from tree_sitter import Language, Node, Parser
from tree_sitter_typescript import language_tsx, language_typescript

from .check_no_response_model import read_baseline

_ROOT = Path(__file__).resolve().parents[2]
_MARKER = re.compile(r"^\s*(?://|#|/\*)\s*test-flakes: allow\s+.*\w")
Kind = Literal["sleep", "skip"]
Finding = tuple[int, Kind, bool]
_KINDS: tuple[Kind, ...] = ("sleep", "skip")
_HEADER = """\
# Test {kind} violations that predate the rule.
#
# GENERATED. Do not edit by hand. To regenerate after removing a use:
#   uv run --no-sync python -m backend.lint.check_test_flakes --write-baseline
#
# Do not regenerate to admit a new use.
#
# One `<count> <path>` per line, sorted by path.
"""


def _python_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_python_name(node.value)}.{node.attr}"
    return ""


def _python_has_reason(value: ast.expr) -> bool:
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "format"
        and isinstance(value.func.value, ast.Constant)
        and isinstance(value.func.value.value, str)
    ):
        try:
            fields = list(Formatter().parse(value.func.value.value))
        except ValueError:
            return False
        return any(literal.strip() for literal, *_ in fields)
    parts = value.values if isinstance(value, ast.JoinedStr) else [value]
    return any(
        isinstance(part, ast.Constant)
        and isinstance(part.value, str)
        and bool(part.value.strip())
        for part in parts
    )


def python_findings(source: str) -> Iterator[Finding]:
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    imports = {
        alias.asname or alias.name: f"{node.module}.{alias.name}"
        for node in nodes
        if isinstance(node, ast.ImportFrom)
        and node.module in {"time", "asyncio", "pytest"}
        for alias in node.names
    }
    imports.update(
        (alias.asname or alias.name, alias.name)
        for node in nodes
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name in {"time", "asyncio", "pytest"}
    )
    marked = {
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT and _MARKER.match(token.string)
    }
    called = {id(node.func) for node in nodes if isinstance(node, ast.Call)}
    for node in nodes:
        if not isinstance(node, ast.Call | ast.Attribute | ast.Name):
            continue
        if id(node) in called:
            continue
        name = _python_name(node.func if isinstance(node, ast.Call) else node)
        head, dot, tail = name.partition(".")
        name = imports.get(head, head) + dot + tail
        if isinstance(node, ast.Call) and name in {"time.sleep", "asyncio.sleep"}:
            yield node.lineno, "sleep", node.lineno in marked
        elif name in {"pytest.mark.skip", "pytest.mark.skipif", "pytest.skip"}:
            if not isinstance(node, ast.Call) and name == "pytest.skip":
                continue
            reason = False
            if isinstance(node, ast.Call):
                values = [kw.value for kw in node.keywords if kw.arg == "reason"]
                if name == "pytest.skip":
                    values.extend(node.args[:1])
                reason = any(_python_has_reason(value) for value in values)
            yield node.lineno, "skip", reason or node.lineno in marked


def _descendants(root: Node) -> Iterator[Node]:
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.named_children))


def _ts_text(node: Node) -> str:
    return (node.text or b"").decode()


def _playwright_test_names(nodes: list[Node]) -> set[str]:
    names = {"test"}
    for node in nodes:
        if node.type != "import_statement":
            continue
        source = node.child_by_field_name("source")
        if source is None or _ts_text(source)[1:-1] != "@playwright/test":
            continue
        for entry in _descendants(node):
            if entry.type != "import_specifier":
                continue
            name = entry.child_by_field_name("name")
            alias = entry.child_by_field_name("alias")
            if name is not None and _ts_text(name) == "test" and alias is not None:
                names.add(_ts_text(alias))
    return names


def _is_playwright_test(receiver: Node, test_names: set[str]) -> bool:
    if receiver.type == "member_expression":
        prop = receiver.child_by_field_name("property")
        target = receiver.child_by_field_name("object")
        if prop is None or _ts_text(prop) != "describe" or target is None:
            return False
        receiver = target
    return receiver.type == "identifier" and _ts_text(receiver) in test_names


def playwright_findings(source: str, *, tsx: bool = False) -> Iterator[Finding]:
    grammar = language_tsx() if tsx else language_typescript()
    nodes = list(
        _descendants(Parser(Language(grammar)).parse(source.encode()).root_node)
    )
    test_names = _playwright_test_names(nodes)
    marked = {
        node.start_point.row + 1
        for node in nodes
        if node.type == "comment" and _MARKER.match(_ts_text(node))
    }
    for node in nodes:
        if node.type != "call_expression":
            continue
        callee = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        if callee is None or args is None:
            continue
        prop = callee.child_by_field_name("property")
        if prop is None:
            continue
        method = _ts_text(prop)
        line = prop.start_point.row + 1
        if method == "waitForTimeout":
            yield line, "sleep", line in marked
        elif method in {"skip", "fixme"} and _is_playwright_test(
            callee.child_by_field_name("object") or callee, test_names
        ):
            values = [arg for arg in args.named_children if arg.type != "comment"]
            # A title plus a test body declares a disabled test. Its title
            # is not a reason. A condition plus a description is a modifier.
            reason = (
                len(values) == 2
                and values[0].type not in {"string", "template_string"}
                and values[1].type in {"string", "template_string"}
                and any(
                    part.type == "string_fragment" and _ts_text(part).strip()
                    for part in values[1].named_children
                )
            )
            yield line, "skip", reason or line in marked


def scan(root: Path) -> Iterator[tuple[str, Finding]]:
    paths = (root / "backend/tests").rglob("*.py")
    for path in sorted(paths):
        source = path.read_text(encoding="utf-8")
        if any(word in source for word in ("sleep", "skip", "mark")):
            for finding in python_findings(source):
                yield path.relative_to(root).as_posix(), finding
    for path in sorted((root / "web/tests").rglob("*.ts*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        source = path.read_text(encoding="utf-8")
        if any(word in source for word in ("waitForTimeout", "skip", "fixme")):
            for finding in playwright_findings(source, tsx=path.suffix == ".tsx"):
                yield path.relative_to(root).as_posix(), finding


def check(root: Path, baseline_dir: Path, *, write: bool = False) -> int:
    violations: dict[Kind, dict[str, list[int]]] = {"sleep": {}, "skip": {}}
    for path, (line, kind, allowed) in scan(root):
        if not allowed:
            violations[kind].setdefault(path, []).append(line)
    failed = False
    for kind in _KINDS:
        path = baseline_dir / f"test_{kind}_baseline.txt"
        found = violations[kind]
        if write:
            rows = [f"{len(lines)} {file}\n" for file, lines in sorted(found.items())]
            path.write_text(_HEADER.format(kind=kind) + "".join(rows), encoding="utf-8")
            continue
        baseline = read_baseline(path)
        for file in sorted(found.keys() | baseline.keys()):
            lines = found.get(file, [])
            allowed = baseline.get(file, 0)
            if len(lines) == allowed:
                continue
            failed = True
            print(
                f"{file}: {len(lines)} test {kind} violations, baseline has {allowed}"
            )
            if len(lines) > allowed:
                for line in sorted(lines):
                    print(f"  {file}:{line}")
    if failed:
        print(
            "Wait for the condition. Use the backend integration manager's wait_for_*"
        )
        print("helper, threading.Event.wait for thread coordination, or Playwright")
        print("locator assertions and expect.poll for values.")
        print("Give each skip a nonempty reason. For a deliberate exception, use")
        print("'test-flakes: allow <reason>' in a comment on the same line.")
        print("After removing a violation, regenerate with --write-baseline.")
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    return check(_ROOT, Path(__file__).resolve().parent, write=args.write_baseline)


if __name__ == "__main__":
    raise SystemExit(main())
