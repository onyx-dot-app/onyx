#!/usr/bin/env python3
"""Fail when a file outside the db directories gains a database operation.

Database operations belong in `backend/onyx/db` and `backend/ee/onyx/db`. This
check counts two shapes in each application file outside those directories:

- A SQLAlchemy statement is built: a call to `select`, `update`, `delete`,
  `insert` or `text` that the file imports from `sqlalchemy`.
- A SQLAlchemy session, connection or engine reads or writes: a call to one of
  `_SESSION_OPERATIONS` on a name the file binds to such an object.

Transaction control (`commit`, `flush`, `rollback`, `refresh`) is not counted,
because the caller that owns the transaction needs it. A session that is passed
to another function is not counted.

The existing operations are frozen in a baseline: for each file, the number of
lines that hold an operation. The check fails when a count rises above the baseline, and when a count falls
below it, so the baseline can only go down.

Usage, from the repo root:
    python3 backend/lint/check_db_ops_outside_db.py            # check all files
    python3 backend/lint/check_db_ops_outside_db.py <path> ... # check these files
    python3 backend/lint/check_db_ops_outside_db.py --write-baseline
"""

import argparse
import ast
import io
import re
import tokenize
from collections.abc import Iterable
from pathlib import Path

# A deliberate exception opts out with a comment that gives a reason: on the
# line of the call, or on its own line above the statement.
ALLOW_MARKER = "db-ops-outside-db: allow"
_ALLOW_WITH_REASON = re.compile(re.escape(ALLOW_MARKER) + r"[\s:(-]*\w")

_REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).resolve().with_name("db_ops_outside_db_baseline.txt")
_BASELINE_HEADER = """\
# Database operations outside backend/onyx/db and backend/ee/onyx/db.
# Each line is `<path> <count>`. The count for a file can only go down.
# Move a query into the db directories, then regenerate:
#   python3 backend/lint/check_db_ops_outside_db.py --write-baseline
"""

# Application code. Migrations, tests and operational scripts are out of scope.
_CHECKED_DIRS = ("backend/onyx/", "backend/ee/onyx/")
_DB_DIRS = ("backend/onyx/db/", "backend/ee/onyx/db/")
# The PostgreSQL implementation of CacheBackend. Its queries belong there.
_EXEMPT_FILES = frozenset({"backend/onyx/cache/postgres_backend.py"})

_STATEMENT_BUILDERS = frozenset({"select", "update", "delete", "insert", "text"})
_SESSION_OPERATIONS = frozenset(
    {
        "execute",
        "scalars",
        "scalar",
        "query",
        "get",
        "get_one",
        "add",
        "add_all",
        "delete",
        "merge",
        "exec_driver_sql",
    }
)
_SESSION_TYPES = frozenset(
    {
        "Session",
        "AsyncSession",
        "Connection",
        "AsyncConnection",
        "Engine",
        "AsyncEngine",
    }
)
# `engine.connect()` and `session.begin_nested()` give another such object.
_SESSION_DERIVING_METHODS = frozenset({"connect", "begin", "begin_nested"})
# Submodules a file may import by name and then qualify a session type or a
# statement builder with, as in `orm.Session` or `sql.select`.
_SQLALCHEMY_SUBMODULES = frozenset(
    {"orm", "engine", "ext", "asyncio", "sql", "expression", "dialects", "postgresql"}
)
_SESSION_FACTORY_MODULE = re.compile(r"^(ee\.)?onyx\.db\.engine(\.|$)")
# Other imports from the engine package do not return a session.
_SESSION_FACTORY_NAME = re.compile(r"session|engine", re.IGNORECASE)
# The name the codebase gives a session, including where it has no annotation.
_SESSION_NAME = "db_session"


def _terminal_name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _is_sqlalchemy(module: str | None) -> bool:
    return module is not None and (
        module == "sqlalchemy" or module.startswith("sqlalchemy.")
    )


class _Imports:
    """The local names a file gives to SQLAlchemy and to the session factories."""

    def __init__(self, tree: ast.AST) -> None:
        self.modules: set[str] = set()
        self.builders: set[str] = set()
        self.session_types: set[str] = set()
        self.session_factories: set[str] = set()
        # Modules whose functions return sessions, such as `sql_engine`.
        self.factory_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_sqlalchemy(alias.name):
                        # `import sqlalchemy.sql` binds the name `sqlalchemy`.
                        self.modules.add(alias.asname or alias.name.split(".")[0])
                        if alias.asname is None:
                            # `sqlalchemy.orm.Session` ends in the submodule name.
                            self.modules.add(alias.name.split(".")[-1])
                    elif _SESSION_FACTORY_MODULE.match(alias.name):
                        self.factory_modules.add(
                            alias.asname or alias.name.split(".")[-1]
                        )
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self._add(node.module, alias.name, alias.asname or alias.name)

    def _add(self, module: str | None, name: str, local: str) -> None:
        if _is_sqlalchemy(module):
            if name in _STATEMENT_BUILDERS:
                self.builders.add(local)
            elif name in _SESSION_TYPES:
                self.session_types.add(local)
            elif name in _SQLALCHEMY_SUBMODULES:
                self.modules.add(local)
        elif module and _SESSION_FACTORY_MODULE.match(module):
            # The name may be a factory function or a module of factories.
            self.factory_modules.add(local)
            if _SESSION_FACTORY_NAME.search(name):
                self.session_factories.add(local)

    def is_qualified_session_type(self, node: ast.expr) -> bool:
        """`orm.Session` or `sqlalchemy.orm.Session`."""
        return (
            isinstance(node, ast.Attribute)
            and node.attr in _SESSION_TYPES
            and _terminal_name(node.value) in self.modules | {"orm", "asyncio"}
        )

    def creates_session(self, func: ast.expr) -> bool:
        """A call of `func` returns a new session, connection or engine."""
        if isinstance(func, ast.Name):
            return func.id in self.session_factories | self.session_types
        return self.is_qualified_session_type(func) or self.is_qualified_factory(func)

    def is_qualified_factory(self, node: ast.expr) -> bool:
        """`sql_engine.get_session_with_tenant`."""
        return (
            isinstance(node, ast.Attribute)
            and bool(_SESSION_FACTORY_NAME.search(node.attr))
            and _terminal_name(node.value) in self.factory_modules
        )

    def is_builder(self, func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            return func.id in self.builders
        return (
            isinstance(func, ast.Attribute)
            and func.attr in _STATEMENT_BUILDERS
            and isinstance(func.value, ast.Name)
            and func.value.id in self.modules
        )

    def is_session_type(self, annotation: ast.expr | None) -> bool:
        """True for `Session`, `Session | None`, `Optional[Session]` and
        `Annotated[Session, ...]`. A container such as `dict[str, Engine]` is not one."""
        if annotation is None:
            return False
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                annotation = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return False
        if isinstance(annotation, ast.Name):
            return annotation.id in self.session_types
        if isinstance(annotation, ast.Attribute):
            return self.is_qualified_session_type(annotation)
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            return self.is_session_type(annotation.left) or self.is_session_type(
                annotation.right
            )
        if isinstance(annotation, ast.Subscript) and _terminal_name(
            annotation.value
        ) in {"Optional", "Annotated"}:
            inner = annotation.slice
            first = inner.elts[0] if isinstance(inner, ast.Tuple) else inner
            return self.is_session_type(first)
        return False


def _session_names(tree: ast.AST, imports: _Imports) -> set[str]:
    """Names and attributes the file binds to a session, connection or engine.

    File-wide rather than per scope: one name rarely holds a session in one
    function and another kind of object in the next."""
    names = {_SESSION_NAME}

    def gives_session(value: ast.expr | None) -> bool:
        if isinstance(value, ast.Await):
            value = value.value
        if _terminal_name(value) in names:
            return True
        if not isinstance(value, ast.Call):
            return False
        func = value.func
        if imports.creates_session(func):
            return True
        return (
            isinstance(func, ast.Attribute)
            and func.attr in _SESSION_DERIVING_METHODS
            and gives_session(func.value)
        )

    def bind(target: ast.expr | None) -> bool:
        name = _terminal_name(target)
        if name is None or name in names:
            return False
        names.add(name)
        return True

    # Repeat until stable, so `self.db = db` after `db: Session` is found in any order.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.arg):
                if imports.is_session_type(node.annotation) and node.arg not in names:
                    names.add(node.arg)
                    changed = True
            elif isinstance(node, ast.AnnAssign):
                if imports.is_session_type(node.annotation) or gives_session(
                    node.value
                ):
                    changed |= bind(node.target)
            elif isinstance(node, ast.Assign):
                if gives_session(node.value):
                    for target in node.targets:
                        changed |= bind(target)
            elif isinstance(node, ast.With | ast.AsyncWith):
                for item in node.items:
                    if gives_session(item.context_expr):
                        changed |= bind(item.optional_vars)
    return names


def _calls_with_statement(tree: ast.AST) -> list[tuple[ast.Call, ast.stmt]]:
    """Every call with the innermost statement that holds it."""
    found: list[tuple[ast.Call, ast.stmt]] = []

    def walk(node: ast.AST, statement: ast.stmt | None) -> None:
        if isinstance(node, ast.stmt):
            statement = node
        if isinstance(node, ast.Call) and statement is not None:
            found.append((node, statement))
        for child in ast.iter_child_nodes(node):
            walk(child, statement)

    walk(tree, None)
    return found


def _comments(source: str) -> dict[int, str]:
    """The comment on each line, so a marker inside a string does not count."""
    comments: dict[int, str] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comments[token.start[0]] = token.string
    return comments


def find_db_operations(source: str) -> tuple[list[int], list[int]]:
    """One-based lines of database operations, and of allow markers with no reason."""
    tree = ast.parse(source)
    lines = source.splitlines()
    comments = _comments(source)
    imports = _Imports(tree)
    sessions = _session_names(tree, imports)
    found: set[int] = set()
    no_reason: set[int] = set()
    for call, statement in _calls_with_statement(tree):
        func = call.func
        is_operation = imports.is_builder(func) or (
            isinstance(func, ast.Attribute)
            and func.attr in _SESSION_OPERATIONS
            and _terminal_name(func.value) in sessions
        )
        if not is_operation:
            continue
        # A trailing marker exempts the call whose name is on its line, so a
        # marker on a nested call does not exempt the call around it. A marker
        # on a comment line above a statement exempts the whole statement; the
        # formatter does not move that one.
        marker_lines = [func.end_lineno or call.lineno]
        above = statement.lineno - 1
        if above >= 1 and lines[above - 1].lstrip().startswith("#"):
            marker_lines.append(above)
        marked = [
            line for line in marker_lines if ALLOW_MARKER in comments.get(line, "")
        ]
        if any(_ALLOW_WITH_REASON.search(comments[line]) for line in marked):
            continue
        no_reason.update(marked)
        found.add(call.lineno)
    return sorted(found), sorted(no_reason)


def is_checked(path: str) -> bool:
    """`path` is relative to the repo root, with forward slashes."""
    return (
        path.endswith(".py")
        and path.startswith(_CHECKED_DIRS)
        and not path.startswith(_DB_DIRS)
        and path not in _EXEMPT_FILES
    )


def _all_checked_files() -> list[str]:
    paths: list[str] = []
    for checked_dir in _CHECKED_DIRS:
        for path in (_REPO_ROOT / checked_dir).rglob("*.py"):
            relative = path.relative_to(_REPO_ROOT).as_posix()
            if is_checked(relative):
                paths.append(relative)
    return sorted(paths)


def _in_checkout(path: str) -> bool:
    """False for a path under a checked directory that this checkout lacks."""
    return any(
        path.startswith(checked_dir) and (_REPO_ROOT / checked_dir).is_dir()
        for checked_dir in _CHECKED_DIRS
    )


def _relative(path: str) -> str | None:
    try:
        return Path(path).resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return None


def read_baseline(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            file_path, count = line.rsplit(maxsplit=1)
            counts[file_path] = int(count)
    return counts


def format_baseline(counts: dict[str, int]) -> str:
    rows = [f"{path} {count}" for path, count in sorted(counts.items()) if count]
    return _BASELINE_HEADER + "\n".join(rows) + "\n"


def check(
    operations: dict[str, list[int]], baseline: dict[str, int], existing: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Compare the scanned files with the baseline.

    Returns the files that have more operations than the baseline allows, each
    with the lines of all its operations, and the baseline entries that are now
    too high. `existing` holds the baseline paths that are still files. A full
    scan passes them all; a scan of some files passes the whole baseline, so a
    deleted file does not fail a commit that did not touch it."""
    risen: list[str] = []
    stale: list[str] = []
    for path, lines in sorted(operations.items()):
        allowed = baseline.get(path, 0)
        if len(lines) > allowed:
            where = ", ".join(str(line) for line in lines)
            risen.append(f"{path}: {len(lines)} (baseline {allowed}), lines {where}")
        elif len(lines) < allowed:
            stale.append(f"{path}: {len(lines)} (baseline {allowed})")
    present = set(existing)
    stale.extend(
        f"{path}: file is gone (baseline {count})"
        for path, count in sorted(baseline.items())
        if path not in present
    )
    return risen, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="files to check (default: all)")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="lower the baseline to the current counts; refuses a rise",
    )
    args = parser.parse_args(argv)

    given = {_relative(path) for path in args.paths}
    # An edit to the baseline is checked against every file it records.
    baseline_given = BASELINE_PATH.relative_to(_REPO_ROOT).as_posix() in given
    full_scan = args.write_baseline or not given or baseline_given
    if full_scan:
        paths = _all_checked_files()
    else:
        paths = sorted(path for path in given if path and is_checked(path))

    operations: dict[str, list[int]] = {}
    no_reason: list[str] = []
    for path in paths:
        file_path = _REPO_ROOT / path
        if not file_path.is_file():
            continue
        try:
            found, unexplained = find_db_operations(file_path.read_text())
        except SyntaxError as e:
            print(f"{path}:{e.lineno}: cannot parse, so its operations are not counted")
            return 1
        operations[path] = found
        no_reason.extend(f"{path}:{line}" for line in unexplained)

    has_baseline = BASELINE_PATH.is_file()
    baseline = read_baseline(BASELINE_PATH) if has_baseline else {}
    # The FOSS mirror has no backend/ee. Its baseline entries stay as they are.
    not_checked_out = {
        path: count for path, count in baseline.items() if not _in_checkout(path)
    }
    # pre-commit does not pass deleted files, so only a full scan reports them.
    existing = [
        path
        for path in baseline
        if not full_scan or path in not_checked_out or (_REPO_ROOT / path).is_file()
    ]
    risen, stale = check(operations, baseline, existing)

    if args.write_baseline:
        if no_reason:
            print(f"`# {ALLOW_MARKER}` needs a reason after it:")
            print("\n".join(f"  {entry}" for entry in no_reason))
            return 1
        # Regeneration lowers counts. A rise needs a marker or an edit by hand.
        if risen and has_baseline:
            print("The baseline can only go down. These files have new operations:")
            print("\n".join(f"  {entry}" for entry in risen))
            return 1
        counts = {path: len(lines) for path, lines in operations.items()}
        BASELINE_PATH.write_text(format_baseline(counts | not_checked_out))
        total = sum(counts.values())
        files = sum(1 for count in counts.values() if count)
        print(f"Wrote {total} database operations in {files} files to {BASELINE_PATH}")
        return 0

    if risen:
        print(
            "New database operations outside backend/onyx/db and backend/ee/onyx/db.\n"
            "Move the query into a function under one of those directories and call it:"
        )
        print("\n".join(f"  {entry}" for entry in risen))
        print(
            f"A deliberate exception may carry `# {ALLOW_MARKER} <reason>` on its "
            "line, or on a comment line above the statement."
        )
    if no_reason:
        print(f"`# {ALLOW_MARKER}` needs a reason after it:")
        print("\n".join(f"  {entry}" for entry in no_reason))
    if stale:
        print(
            "Fewer database operations than the baseline records. Lower the baseline:\n"
            "  python3 backend/lint/check_db_ops_outside_db.py --write-baseline"
        )
        print("\n".join(f"  {entry}" for entry in stale))
    return 1 if risen or no_reason or stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
