#!/usr/bin/env python3
"""Fail when a backend import crosses a boundary in import_boundaries.toml.

Each contract in backend/import_boundaries.toml names code that must not
import other code. The check reads every `import` and `from ... import`
statement, at any depth: module level, inside a function, and under
`TYPE_CHECKING`. Imports made from a string, such as
`fetch_versioned_implementation`, are not statements and are not checked.

Paths decide which contract applies, so directories without `__init__.py`
and directories that ship outside the backend image are covered.

Usage, from the repo root:
    python3 backend/scripts/check_import_boundaries.py            # whole tree
    python3 backend/scripts/check_import_boundaries.py backend/onyx/db/user.py ...

Standard library only: the hook runs without the backend virtualenv.
"""

import ast
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACKEND_DIR / "import_boundaries.toml"
_SKIP_DIRS = {".venv", "__pycache__", "node_modules"}
_FORBIDDEN = "forbidden"
_INDEPENDENCE = "independence"
_CONTRACT_KEYS = {
    "name",
    "rule",
    "reason",
    "instead",
    "type",
    "source",
    "source_exclude",
    "forbidden",
    "allowed",
    "container",
    "shared",
    "exception",
}
_EXCEPTION_KEYS = {"importer", "imports", "reason"}


class ConfigError(Exception):
    """The contract file is malformed or names something that does not exist."""


@dataclass(frozen=True)
class ImportException:
    importer: str
    imports: str
    reason: str


@dataclass(frozen=True)
class Contract:
    name: str
    rule: str
    reason: str
    instead: str
    kind: str
    # Path prefixes relative to backend/. A directory ends with "/".
    source: tuple[str, ...]
    source_exclude: tuple[str, ...]
    # Dotted module prefixes.
    forbidden: tuple[str, ...]
    allowed: tuple[str, ...]
    # Independence only: the directory whose sub-directories are the siblings,
    # and the siblings that every other sibling may import.
    container: str
    shared: tuple[str, ...]
    exceptions: tuple[ImportException, ...]


@dataclass(frozen=True)
class FoundImport:
    module: str
    line: int


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    module: str
    contract: Contract


def _matches_module(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _matches_path(path: str, prefix: str) -> bool:
    return path.startswith(prefix) if prefix.endswith("/") else path == prefix


def _module_exists(backend_dir: Path, module: str) -> bool:
    """True for a package, a module, or a name defined in a module."""
    parts = module.split(".")
    for candidate in (parts, parts[:-1]):
        if not candidate:
            continue
        base = backend_dir.joinpath(*candidate)
        if base.is_dir() or base.with_suffix(".py").is_file():
            return True
    return False


def _reject_unknown_keys(
    table: Mapping[str, object], known: set[str], where: str
) -> None:
    # A misspelled key would be ignored and could switch off part of a contract.
    unknown = sorted(set(table) - known)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _string(table: Mapping[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: `{key}` must be a non-empty string")
    return value


def _strings(table: Mapping[str, object], key: str, where: str) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: `{key}` must be a list of strings")
    return tuple(str(v) for v in value)


def _parse_exceptions(
    table: Mapping[str, object], where: str, backend_dir: Path
) -> tuple[ImportException, ...]:
    raw = table.get("exception", [])
    if not isinstance(raw, list):
        raise ConfigError(f"{where}: `exception` must be an array of tables")
    exceptions: list[ImportException] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ConfigError(f"{where}: `exception` must be an array of tables")
        entry: dict[str, object] = {str(key): value for key, value in item.items()}
        _reject_unknown_keys(entry, _EXCEPTION_KEYS, f"{where} exception")
        exception = ImportException(
            importer=_string(entry, "importer", f"{where} exception"),
            imports=_string(entry, "imports", f"{where} exception"),
            reason=_string(entry, "reason", f"{where} exception"),
        )
        if not (backend_dir / exception.importer).is_file():
            raise ConfigError(
                f"{where}: exception importer `{exception.importer}` does not exist"
            )
        exceptions.append(exception)
    return tuple(exceptions)


def _parse_contract(table: Mapping[str, object], backend_dir: Path) -> Contract:
    name = _string(table, "name", "contract")
    where = f"contract `{name}`"
    _reject_unknown_keys(table, _CONTRACT_KEYS, where)
    kind = str(table.get("type", _FORBIDDEN))
    if kind not in (_FORBIDDEN, _INDEPENDENCE):
        raise ConfigError(f"{where}: unknown type `{kind}`")

    contract = Contract(
        name=name,
        rule=_string(table, "rule", where),
        reason=_string(table, "reason", where),
        instead=_string(table, "instead", where),
        kind=kind,
        source=_strings(table, "source", where),
        source_exclude=_strings(table, "source_exclude", where),
        forbidden=_strings(table, "forbidden", where),
        allowed=_strings(table, "allowed", where),
        container=str(table.get("container", "")).rstrip("/"),
        shared=_strings(table, "shared", where),
        exceptions=_parse_exceptions(table, where, backend_dir),
    )

    # A path or module that no longer exists would switch the contract off
    # without a failure, so a rename must update the contract.
    if kind == _INDEPENDENCE:
        if not (backend_dir / contract.container).is_dir() or not contract.container:
            raise ConfigError(f"{where}: container `{contract.container}` not found")
        for sibling in contract.shared:
            if not (backend_dir / contract.container / sibling).is_dir():
                raise ConfigError(f"{where}: shared sibling `{sibling}` not found")
        return contract

    if not contract.source or not contract.forbidden:
        raise ConfigError(f"{where}: `source` and `forbidden` must not be empty")
    for prefix in contract.source + contract.source_exclude:
        if not (backend_dir / prefix).exists():
            raise ConfigError(f"{where}: path `{prefix}` does not exist")
        if (backend_dir / prefix).is_dir() != prefix.endswith("/"):
            raise ConfigError(f"{where}: end a directory with `/`: `{prefix}`")
    for module in contract.forbidden + contract.allowed:
        if not _module_exists(backend_dir, module):
            raise ConfigError(f"{where}: module `{module}` does not exist")
    return contract


def load_contracts(config_path: Path, backend_dir: Path) -> list[Contract]:
    with config_path.open("rb") as config_file:
        data = tomllib.load(config_file)
    raw = data.get("contract", [])
    if not isinstance(raw, list) or not raw:
        raise ConfigError("no [[contract]] tables found")
    contracts = [_parse_contract(table, backend_dir) for table in raw]
    names = [contract.name for contract in contracts]
    if len(names) != len(set(names)):
        raise ConfigError("contract names must be unique")
    return contracts


class _ImportCollector(ast.NodeVisitor):
    def __init__(self, package_parts: list[str]) -> None:
        self._package_parts = package_parts
        self.found: list[FoundImport] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.found.append(FoundImport(alias.name, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:
            keep = len(self._package_parts) - (node.level - 1)
            parts = self._package_parts[: max(keep, 0)]
            base = ".".join(parts + ([node.module] if node.module else []))
        for alias in node.names:
            # `from a import b` may name the module `a.b`, so report `a.b`.
            module = f"{base}.{alias.name}" if base else alias.name
            self.found.append(FoundImport(module, node.lineno))


def collect_imports(source: str, path: str) -> list[FoundImport]:
    """Every import in `source`. `path` is relative to backend/."""
    parts = path.removesuffix(".py").split("/")
    package_parts = parts[:-1]
    collector = _ImportCollector(package_parts)
    collector.visit(ast.parse(source))
    return collector.found


def _applies(contract: Contract, path: str) -> bool:
    if contract.kind == _INDEPENDENCE:
        # Only files inside a sibling directory, not files in the container.
        inside = path.removeprefix(contract.container + "/")
        return inside != path and "/" in inside
    if any(_matches_path(path, prefix) for prefix in contract.source_exclude):
        return False
    return any(_matches_path(path, prefix) for prefix in contract.source)


def _breaks(contract: Contract, path: str, module: str, backend_dir: Path) -> bool:
    if contract.kind == _INDEPENDENCE:
        container_module = contract.container.replace("/", ".")
        if not _matches_module(module, container_module) or module == container_module:
            return False
        own = path.removeprefix(contract.container + "/").split("/")[0]
        other = module.removeprefix(container_module + ".").split(".")[0]
        if other == own or other in contract.shared:
            return False
        return (backend_dir / contract.container / other).is_dir()
    if any(_matches_module(module, prefix) for prefix in contract.allowed):
        return False
    return any(_matches_module(module, prefix) for prefix in contract.forbidden)


def check_file(
    path: str, source: str, contracts: list[Contract], backend_dir: Path
) -> tuple[list[Violation], list[str]]:
    """Violations in one file, and its recorded exceptions that match nothing."""
    applicable = [contract for contract in contracts if _applies(contract, path)]
    recorded = [
        (contract, exception)
        for contract in contracts
        for exception in contract.exceptions
        if exception.importer == path
    ]
    if not applicable and not recorded:
        return [], []

    imports = collect_imports(source, path)
    violations: list[Violation] = []
    used: set[ImportException] = set()
    for contract in applicable:
        for found in imports:
            if not _breaks(contract, path, found.module, backend_dir):
                continue
            exception = next(
                (
                    e
                    for e in contract.exceptions
                    if e.importer == path and _matches_module(found.module, e.imports)
                ),
                None,
            )
            if exception is None:
                violations.append(Violation(path, found.line, found.module, contract))
            else:
                used.add(exception)

    stale = [
        f"backend/{path}: the exception for `{exception.imports}` in contract "
        f"`{contract.name}` matches no import. Remove it from "
        f"backend/{CONFIG_PATH.name}."
        for contract, exception in recorded
        if exception not in used
    ]
    return violations, stale


def _all_files(contracts: list[Contract], backend_dir: Path) -> list[str]:
    roots: set[str] = set()
    for contract in contracts:
        if contract.kind == _INDEPENDENCE:
            roots.add(contract.container + "/")
        roots.update(contract.source)
        roots.update(exception.importer for exception in contract.exceptions)

    files: set[str] = set()
    for root in roots:
        base = backend_dir / root
        if base.is_file():
            files.add(root)
            continue
        for found in base.rglob("*.py"):
            relative = found.relative_to(backend_dir)
            if not _SKIP_DIRS.intersection(relative.parts):
                files.add(relative.as_posix())
    return sorted(files)


def _requested_files(arguments: list[str], backend_dir: Path) -> list[str] | None:
    """Backend-relative paths to check, or None to check the whole tree."""
    files: list[str] = []
    for argument in arguments:
        resolved = Path(argument).resolve()
        if resolved in (CONFIG_PATH, Path(__file__).resolve()):
            return None
        if resolved.suffix != ".py" or not resolved.is_file():
            continue
        if resolved.is_relative_to(backend_dir):
            files.append(resolved.relative_to(backend_dir).as_posix())
    return files


def format_violation(violation: Violation) -> str:
    contract = violation.contract
    return (
        f"backend/{violation.path}:{violation.line}: "
        f"imports `{violation.module}`\n"
        f"  contract: {contract.name}: {contract.rule}\n"
        f"  why:      {contract.reason}\n"
        f"  instead:  {contract.instead}"
    )


def main(arguments: list[str]) -> int:
    try:
        contracts = load_contracts(CONFIG_PATH, BACKEND_DIR)
    except (ConfigError, tomllib.TOMLDecodeError) as error:
        print(f"backend/{CONFIG_PATH.name}: {error}")
        return 2

    files = _requested_files(arguments, BACKEND_DIR) if arguments else None
    if files is None:
        files = _all_files(contracts, BACKEND_DIR)

    violations: list[Violation] = []
    stale: list[str] = []
    for path in files:
        try:
            source = (BACKEND_DIR / path).read_text(encoding="utf-8")
            file_violations, file_stale = check_file(
                path, source, contracts, BACKEND_DIR
            )
        except (SyntaxError, UnicodeDecodeError):
            # Ruff reports a file that does not parse.
            continue
        violations.extend(file_violations)
        stale.extend(file_stale)

    for violation in violations:
        print(format_violation(violation) + "\n")
    for message in stale:
        print(message + "\n")
    if violations:
        print(
            f"{len(violations)} import boundary violation(s). The contracts are in "
            f"backend/{CONFIG_PATH.name}. Move the code as `instead` says. For a "
            "deliberate import, add a [[contract.exception]] entry with a reason."
        )
    return 1 if violations or stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
