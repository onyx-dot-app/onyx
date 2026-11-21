#!/usr/bin/env python3
"""Fail when a FastAPI route declares its response type with `response_model=`.

The return annotation of the handler is the response type: FastAPI reads it
when the keyword is absent, and the type checker reads it too. A separate
`response_model=` can drift from what the handler returns.

`response_model=None` is not flagged. It declares no type; it tells FastAPI
to build no response model from an annotation such as `Model | JSONResponse`.

The baseline holds the number of uses in each file that predate the rule. The
check fails when a file's count differs from its baseline: a higher count is a
new use, and a lower count needs a regenerated baseline so the count cannot
rise again.

Usage, from any directory:
    python3 backend/lint/check_no_response_model.py
    python3 backend/lint/check_no_response_model.py --write-baseline
"""

import argparse
import ast
import io
import re
import tokenize
from pathlib import Path

# A deliberate exception opts out on the decorator or call, and must say why.
ALLOW_MARKER = "no-response-model: allow"
_MARKER_WITH_REASON = re.compile(re.escape(ALLOW_MARKER) + r"\s*\S*\w")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_DIRS = ("backend/onyx", "backend/ee", "backend/model_server")
BASELINE_PATH = Path(__file__).resolve().parent / "no_response_model_baseline.txt"
_BASELINE_HEADER = """\
# Uses of `response_model=` on FastAPI routes that predate the rule.
#
# GENERATED. Do not edit by hand. To regenerate after you remove a use:
#   python3 backend/lint/check_no_response_model.py --write-baseline
#
# Do not regenerate to admit a new use. Type the handler's return instead.
#
# One `<count> <path>` per line, sorted by path.
"""
# Decorator methods of `APIRouter` and `FastAPI` that take `response_model`.
_ROUTE_DECORATORS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "trace",
    "api_route",
}
_KEYWORD = "response_model"


def _is_route_call(call: ast.Call, is_decorator: bool) -> bool:
    """`@<router>.get(...)` and its siblings, or `<router>.add_api_route(...)`.

    A plain call such as `client.get(url, response_model=...)` is not a route."""
    if not isinstance(call.func, ast.Attribute):
        return False
    if is_decorator:
        return call.func.attr in _ROUTE_DECORATORS
    return call.func.attr == "add_api_route"


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _marker_comments(source: str) -> dict[int, str]:
    """Comments that hold the marker, by line. A string literal is not a marker."""
    return {
        token.start[0]: token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT and ALLOW_MARKER in token.string
    }


def find_response_models(source: str) -> list[tuple[int, str]]:
    """One-based line and problem for each route that sets `response_model`."""
    markers = _marker_comments(source) if ALLOW_MARKER in source else {}
    tree = ast.parse(source)
    decorators = {
        id(decorator)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        for decorator in node.decorator_list
    }
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_route_call(node, is_decorator=id(node) in decorators):
            continue
        keyword = next(
            (
                keyword
                for keyword in node.keywords
                if keyword.arg == _KEYWORD and not _is_none(keyword.value)
            ),
            None,
        )
        if keyword is None:
            continue
        marked = [
            markers[line]
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1)
            if line in markers
        ]
        if not marked:
            found.append((keyword.lineno, "response_model= on a route"))
        elif not any(_MARKER_WITH_REASON.search(line) for line in marked):
            found.append((keyword.lineno, "allow marker without a reason"))
    return sorted(found)


def scan(root: Path) -> dict[str, list[tuple[int, str]]]:
    """Problems of each file under the scanned directories, by repo-root path."""
    problems: dict[str, list[tuple[int, str]]] = {}
    for directory in _SCANNED_DIRS:
        for path in sorted((root / directory).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            # Skip the parse for the many files that cannot hold a use.
            if _KEYWORD not in source:
                continue
            found = find_response_models(source)
            if found:
                problems[path.relative_to(root).as_posix()] = found
    return problems


def read_baseline(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    baseline: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        count, file = line.split(maxsplit=1)
        baseline[file] = int(count)
    return baseline


def write_baseline(path: Path, problems: dict[str, list[tuple[int, str]]]) -> None:
    rows = [f"{len(found)} {file}\n" for file, found in sorted(problems.items())]
    path.write_text(_BASELINE_HEADER + "".join(rows), encoding="utf-8")


def check(root: Path, baseline_path: Path) -> int:
    problems = scan(root)
    baseline = read_baseline(baseline_path)
    new: list[str] = []
    stale: list[str] = []
    for file in sorted(problems.keys() | baseline.keys()):
        found = problems.get(file, [])
        allowed = baseline.get(file, 0)
        if len(found) > allowed:
            new.append(f"  {file}: {len(found)} uses, the baseline allows {allowed}")
            new.extend(f"    {file}:{line}: {problem}" for line, problem in found)
        elif len(found) < allowed:
            stale.append(f"  {file}: {len(found)} uses, the baseline has {allowed}")
    if new:
        print("Do not set `response_model=` on a FastAPI route:")
        print("\n".join(new))
        print(
            "Remove the keyword and put the type on the return annotation of the "
            "handler, for example `def handler(...) -> MyResponse:`."
        )
        print(
            f"A deliberate exception may carry `# {ALLOW_MARKER} <reason>` on the "
            "decorator. The reason is required."
        )
    if stale:
        print("The response_model baseline is stale:")
        print("\n".join(stale))
        print(
            "Regenerate it: python3 backend/lint/check_no_response_model.py "
            "--write-baseline"
        )
    return 1 if new or stale else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record the current count of each file as the baseline",
    )
    args = parser.parse_args(argv)
    if args.write_baseline:
        write_baseline(BASELINE_PATH, scan(_REPO_ROOT))
        return 0
    return check(_REPO_ROOT, BASELINE_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
