#!/usr/bin/env python3
"""Fail when a file gains an `HTTPException` or a `fastapi`/`starlette` status constant.

API code raises `OnyxError` with an `OnyxErrorCode` (backend/AGENTS.md, "Error
Handling"). Violations that predate the check are recorded per file in the
baseline. A file fails when its count is not the baseline count: above it, the
change added a violation; below it, the baseline must be lowered to keep the gain.

A violation is one of:
  * a call of, a subclass of, or a bare `raise` of `HTTPException` from
    `fastapi` or `starlette`
  * a use of a constant from `fastapi.status` or `starlette.status`

Catching `HTTPException` and `isinstance` checks are not violations.

The check reads names through the imports of the file. It does not follow an
alias such as `E = HTTPException`, a star import or a re-export.

Usage, from the repo root:
    python3 backend/lint/check_no_http_exception.py
    python3 backend/lint/check_no_http_exception.py --write-baseline
"""

import argparse
import ast
import io
import re
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).resolve().with_name("no_http_exception_baseline.txt")
# Apps with no OnyxError handler are out of scope: model_server, and the sandbox
# daemon, which runs in the sandbox image without the onyx package.
SCAN_ROOTS = ("backend/onyx", "backend/ee")
# The FOSS mirror removes the enterprise code, so its baseline rows do not apply there.
ENTERPRISE_ROOT = "backend/ee/"
ENTERPRISE_PACKAGE = "backend/ee/onyx"
SKIP_PREFIXES = ("backend/onyx/server/features/build/sandbox/image/sandbox_daemon/",)
# A deliberate exception goes on or directly above the violation and must give a reason.
ALLOW_MARKER = "http-exception: allow"
_ALLOW_WITH_REASON = re.compile(rf"{re.escape(ALLOW_MARKER)}\b[\s:(—-]*\w")
_BANNED_MODULES = ("fastapi", "starlette")
_HTTP_EXCEPTIONS = {
    "fastapi.HTTPException",
    "fastapi.exceptions.HTTPException",
    "starlette.exceptions.HTTPException",
}
_STATUS_CONSTANT = re.compile(r"^(?:fastapi|starlette)\.status\.(?:HTTP|WS)_\d+_\w+$")
# Every violation names one of these, so other files need no parse.
_TEXT_GATE = re.compile(r"HTTPException|\b(?:HTTP|WS)_\d")
_SIMPLE_STATEMENTS = (ast.Assign, ast.AnnAssign, ast.Expr, ast.Raise, ast.Return)
_BASELINE_HEADER = """\
# Per-file counts of HTTPException and fastapi/starlette status-constant uses that
# predate the check in backend/lint/check_no_http_exception.py. Do not add
# entries or raise a count: raise OnyxError instead (backend/AGENTS.md, "Error
# Handling"). After you remove violations, regenerate with:
#   python3 backend/lint/check_no_http_exception.py --write-baseline
"""
_FIX = (
    "Raise `OnyxError(OnyxErrorCode.X, detail)` from `onyx.error_handling.exceptions`. "
    "For an upstream status code, pass `status_code_override=`. "
    'See "Error Handling" in backend/AGENTS.md. A deliberate exception carries '
    f"`# {ALLOW_MARKER} <reason>` on or directly above the line."
)


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name to qualified name, for every import in the file.

    Scopes are not tracked. When a name is imported twice, the fastapi or
    starlette import wins, so a nested import cannot hide a violation."""
    aliases: dict[str, str] = {}

    def bind(local: str, qualified: str) -> None:
        if aliases.get(local, "").split(".")[0] not in _BANNED_MODULES:
            aliases[local] = qualified

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                bind(alias.asname or alias.name, f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bind(alias.asname, alias.name)
                else:
                    head = alias.name.split(".")[0]
                    bind(head, head)
    return aliases


def _allow_lines(source: str) -> tuple[set[int], set[int]]:
    """One-based lines that carry the marker in a comment, and comment-only lines."""
    allow: set[int] = set()
    comment_only: set[int] = set()
    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        line = token.start[0]
        if _ALLOW_WITH_REASON.search(token.string):
            allow.add(line)
        if lines[line - 1].lstrip().startswith("#"):
            comment_only.add(line)
    return allow, comment_only


class _Finder(ast.NodeVisitor):
    def __init__(
        self, aliases: dict[str, str], allow: set[int], comment_only: set[int]
    ) -> None:
        self._aliases = aliases
        self._allow = allow
        self._comment_only = comment_only
        self._statement: ast.stmt | None = None
        self.found: set[tuple[int, int]] = set()

    def _qualified(self, node: ast.expr) -> str | None:
        dotted = _dotted(node)
        if dotted is None:
            return None
        head, _, rest = dotted.partition(".")
        if head not in self._aliases:
            return None
        return f"{self._aliases[head]}.{rest}" if rest else self._aliases[head]

    def visit(self, node: ast.AST) -> None:
        # Restore on exit: a decorator is visited after the function body.
        enclosing = self._statement
        if isinstance(node, ast.stmt):
            self._statement = node
        super().visit(node)
        self._statement = enclosing

    def _allowed_above(self, line: int) -> bool:
        """The marker is on `line` or in the comment lines directly above it."""
        if line in self._allow:
            return True
        line -= 1
        while line in self._comment_only:
            if line in self._allow:
                return True
            line -= 1
        return False

    def _flag(self, node: ast.expr | ast.stmt, name: ast.expr) -> None:
        """Flag `node` at `name`, unless the marker allows it.

        The marker goes on a line of the violation or directly above it. A
        marker on the first line of a simple statement, or directly above it,
        covers the statement. A compound statement, such as a `def`, does not
        pass a marker to its body."""
        last = node.end_lineno or node.lineno
        if any(line in self._allow for line in range(node.lineno, last + 1)):
            return
        if self._allowed_above(node.lineno):
            return
        statement = self._statement
        if isinstance(statement, _SIMPLE_STATEMENTS) and self._allowed_above(
            statement.lineno
        ):
            return
        self.found.add((name.lineno, name.col_offset))

    def _is_http_exception(self, node: ast.expr | None) -> bool:
        return node is not None and self._qualified(node) in _HTTP_EXCEPTIONS

    def visit_Call(self, node: ast.Call) -> None:
        if self._is_http_exception(node.func):
            self._flag(node, node.func)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        if node.exc is not None and self._is_http_exception(node.exc):
            self._flag(node, node.exc)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            if self._is_http_exception(base):
                self._flag(base, base)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._is_status_constant(node):
            self._flag(node, node)
            return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if self._is_status_constant(node):
            self._flag(node, node)

    def _is_status_constant(self, node: ast.expr) -> bool:
        qualified = self._qualified(node)
        return qualified is not None and bool(_STATUS_CONSTANT.match(qualified))


def find_violations(source: str) -> list[int]:
    """One-based line numbers of violations, one entry per violation."""
    if not _TEXT_GATE.search(source):
        return []
    tree = ast.parse(source)
    finder = _Finder(_import_aliases(tree), *_allow_lines(source))
    finder.visit(tree)
    return [line for line, _ in sorted(finder.found)]


def scan(repo_root: Path) -> dict[str, list[int]]:
    """Violation lines for each file that has any. Paths are repo-relative."""
    violations: dict[str, list[int]] = {}
    for root in SCAN_ROOTS:
        for path in sorted((repo_root / root).rglob("*.py")):
            relative = path.relative_to(repo_root).as_posix()
            if relative.startswith(SKIP_PREFIXES):
                continue
            try:
                lines = find_violations(path.read_text(encoding="utf-8"))
            except SyntaxError as e:
                raise SystemExit(f"{relative}: cannot parse: {e}") from e
            if lines:
                violations[relative] = lines
    return violations


def read_baseline(path: Path) -> dict[str, int]:
    baseline: dict[str, int] = {}
    if not path.exists():
        return baseline
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 2 or not fields[1].isdigit() or fields[0] in baseline:
            raise SystemExit(
                f"{path}:{number}: expected one `<path> <count>` row for each file. "
                "Regenerate the file with `--write-baseline`."
            )
        baseline[fields[0]] = int(fields[1])
    return baseline


def format_baseline(violations: dict[str, list[int]]) -> str:
    rows = [
        f"{relative} {len(lines)}\n" for relative, lines in sorted(violations.items())
    ]
    return _BASELINE_HEADER + "".join(rows)


def check(violations: dict[str, list[int]], baseline: dict[str, int]) -> list[str]:
    """Failure messages for each file whose count is not its baseline count."""
    failures: list[str] = []
    for relative in sorted(set(violations) | set(baseline)):
        lines = violations.get(relative, [])
        allowed = baseline.get(relative, 0)
        if len(lines) > allowed:
            where = ", ".join(f"{relative}:{line}" for line in lines)
            failures.append(
                f"{relative}: {len(lines)} violations, baseline allows {allowed}. "
                f"Remove the ones this change added. All of them: {where}"
            )
        elif len(lines) < allowed:
            failures.append(
                f"{relative}: {len(lines)} violations, baseline records {allowed}. "
                "Lower the baseline with `--write-baseline` to keep the gain."
            )
    return failures


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)

    violations = scan(repo_root)
    if args.write_baseline:
        args.baseline.write_text(format_baseline(violations), encoding="utf-8")
        total = sum(len(lines) for lines in violations.values())
        print(f"Wrote {total} violations in {len(violations)} files to {args.baseline}")
        return 0

    baseline = read_baseline(args.baseline)
    if not (repo_root / ENTERPRISE_PACKAGE).is_dir():
        baseline = {
            relative: count
            for relative, count in baseline.items()
            if not relative.startswith(ENTERPRISE_ROOT)
        }
    failures = check(violations, baseline)
    if not failures:
        return 0
    print("HTTPException and fastapi/starlette status constants are not allowed.")
    print("\n".join(f"  {failure}" for failure in failures))
    print(_FIX)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
