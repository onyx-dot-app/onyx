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

from .check_no_response_model import read_baseline

_ROOT = Path(__file__).resolve().parents[2]
_MARKER = re.compile(r"^\s*#\s*test-flakes: allow\s+.*\w")
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


def scan(root: Path) -> Iterator[tuple[str, Finding]]:
    paths = (root / "backend/tests").rglob("*.py")
    for path in sorted(paths):
        source = path.read_text(encoding="utf-8")
        if any(word in source for word in ("sleep", "skip", "mark")):
            for finding in python_findings(source):
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
        print("helper or threading.Event.wait for thread coordination.")
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
