"""Connectors and permission-sync code yield bare external group ids. Storage
adds the source prefix, so a prefix added here would be stored twice."""

import ast
from pathlib import Path

import ee.onyx.external_permissions
import onyx.connectors

PREFIX_FUNCTION = "build_ext_group_name_for_onyx"

FENCED_PACKAGE_FILES: list[str | None] = [
    onyx.connectors.__file__,
    ee.onyx.external_permissions.__file__,
]

# These read stored group ids, so they build the stored form to compare with.
ALLOWED_READERS: set[str] = {
    "external_permissions/azure_datalake/group_sync.py",
    "external_permissions/github/doc_sync.py",
}


def _names_prefix_function(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == PREFIX_FUNCTION:
            return True
        if isinstance(node, ast.Attribute) and node.attr == PREFIX_FUNCTION:
            return True
        if isinstance(node, ast.alias) and node.name == PREFIX_FUNCTION:
            return True
    return False


def _violations(directory: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(directory.rglob("*.py")):
        relative_path = f"{directory.name}/{path.relative_to(directory).as_posix()}"
        if relative_path in ALLOWED_READERS:
            continue
        if _names_prefix_function(ast.parse(path.read_text(), filename=str(path))):
            violations.append(relative_path)
    return violations


def test_connectors_and_perm_sync_do_not_prefix_group_ids() -> None:
    violations: list[str] = []
    for package_file in FENCED_PACKAGE_FILES:
        assert package_file is not None
        violations.extend(_violations(Path(package_file).parent))

    assert not violations, (
        f"{violations} use {PREFIX_FUNCTION}. Yield bare group ids: storage adds "
        "the source prefix."
    )


def test_allowed_readers_still_exist() -> None:
    """Keeps the allow list from holding files that moved or stopped reading."""
    directory = Path(ee.onyx.external_permissions.__file__ or "").parent
    for relative_path in ALLOWED_READERS:
        path = directory.parent / relative_path
        assert _names_prefix_function(ast.parse(path.read_text(), filename=str(path)))
