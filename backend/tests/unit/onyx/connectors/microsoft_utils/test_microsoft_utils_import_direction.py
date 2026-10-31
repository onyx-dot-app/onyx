"""The shared Microsoft packages must not depend on their callers.

Connectors import the packages, never the reverse, and the MIT package never
reaches into Enterprise. Nothing else enforces import direction, and a single
convenience import back into a connector would make a package unusable from
the next one.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[5]
PACKAGE_DIR = BACKEND_DIR / "onyx" / "connectors" / "microsoft_utils"
EE_PACKAGE_DIR = (
    BACKEND_DIR / "ee" / "onyx" / "external_permissions" / "microsoft_utils"
)

# Shared connector infrastructure the packages may use. Everything else under
# `onyx.connectors` is a sibling connector and is off limits.
ALLOWED_CONNECTOR_SUBPACKAGES = {"microsoft_utils", "cross_connector_utils"}


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _modules_in(package_dir: pathlib.Path) -> list[pathlib.Path]:
    files = sorted(package_dir.glob("*.py"))
    assert files, f"no modules found under {package_dir}"
    return files


def _connector_imports(module_path: pathlib.Path) -> set[str]:
    offenders = set()
    for module in _imported_modules(module_path):
        parts = module.split(".")
        if parts[:2] != ["onyx", "connectors"] or len(parts) < 4:
            # Fewer than 4 parts is a top-level helper such as
            # `onyx.connectors.models`, which is shared infrastructure.
            continue
        if parts[2] not in ALLOWED_CONNECTOR_SUBPACKAGES:
            offenders.add(module)
    return offenders


def _module_id(module_path: pathlib.Path) -> str:
    return str(module_path.relative_to(BACKEND_DIR))


@pytest.mark.parametrize("module_path", _modules_in(PACKAGE_DIR), ids=_module_id)
def test_package_does_not_import_enterprise(module_path: pathlib.Path) -> None:
    offenders = {m for m in _imported_modules(module_path) if m.split(".")[0] == "ee"}
    assert not offenders, (
        f"{module_path.name} imports Enterprise code: {sorted(offenders)}. "
        "The MIT package must stay importable without Enterprise."
    )


@pytest.mark.parametrize(
    "module_path",
    _modules_in(PACKAGE_DIR) + _modules_in(EE_PACKAGE_DIR),
    ids=_module_id,
)
def test_package_does_not_import_a_connector(module_path: pathlib.Path) -> None:
    offenders = _connector_imports(module_path)
    assert not offenders, (
        f"{module_path.name} imports a connector: {sorted(offenders)}. "
        "Connectors depend on the package, never the reverse."
    )
