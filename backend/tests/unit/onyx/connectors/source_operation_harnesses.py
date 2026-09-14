"""Reusable logic behind the auto-discovering source-operations harnesses.

The harness tests (coverage and import fence) parametrize over
``registered_source_operations()``; the functions here do the actual work so
they can be unit-tested against synthetic gateways and directories.
"""

import ast
import importlib
import sys
from collections.abc import Collection, Sequence
from pathlib import Path
from unittest.mock import MagicMock, create_autospec

from pydantic import BaseModel, ConfigDict

import ee.onyx.external_permissions
import onyx.connectors
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.source_operations import (
    SourceOperations,
    registered_source_operations,
)


def import_all_source_operation_gateways() -> None:
    """Imports every connector's gateway module so registration fires.

    Asserts every discovered module defines a registered gateway, so discovery
    rot (a rename, a glob mismatch) surfaces as a loud collection error instead
    of vacuously skipped harnesses. Deliberately does NOT assume the directory
    name matches ``source.value`` (``google_site/`` vs ``google_sites``,
    ``blob/`` serving several sources already violate it).
    """
    connectors_dir = Path(onyx.connectors.__file__).parent
    for path in sorted(connectors_dir.glob("*/source_operations.py")):
        module_name = f"onyx.connectors.{path.parent.name}.source_operations"
        importlib.import_module(module_name)
        assert any(
            gateway.__module__ == module_name
            for gateway in registered_source_operations().values()
        ), (
            f"{path} was imported but defines no registered gateway; the "
            "coverage and fence harnesses would silently skip it."
        )


class UncoveredUnit(BaseModel):
    """One (operation, variant, capability) unit no check exercised."""

    model_config = ConfigDict(frozen=True)

    operation: str
    variant: str | None
    capability: CredentialCapability


def compute_uncovered_units(
    gateway_class: type[SourceOperations],
    checks: Sequence[CapabilityCheck],
) -> list[UncoveredUnit]:
    """Runs each check against a spy gateway and returns unexercised units.

    A unit is covered when a check of the unit's capability invoked the
    operation (with ``variant=`` naming the unit's variant, for variant-bearing
    operations). ``untested``-annotated operations are exempt. Checks run
    against mock data and may raise; their valid calls still count. The spy is
    autospecced, so a call whose shape the real operation would reject raises
    and records nothing -- a broken call cannot certify coverage.
    """
    exercised: set[tuple[str, str | None, CredentialCapability]] = set()
    for check in checks:
        spy = create_autospec(gateway_class, instance=True)
        context = CapabilityCheckContext(
            source=gateway_class.source,
            credential_json={},
            connector=MagicMock(spec=BaseConnector),
            connector_specific_config={},
            source_operations=spy,
        )
        try:
            check.run(context)
        except Exception:
            pass
        for name, _args, kwargs in spy.mock_calls:
            # Chained calls (``spy.op().foo()``) yield junk segments like
            # ``op()``; they never match a registered operation name, so they
            # sit harmlessly in the exercised set.
            operation = name.split(".")[0]
            if not operation:
                continue
            exercised.add((operation, kwargs.get("variant"), check.capability))

    uncovered: list[UncoveredUnit] = []
    for operation, spec in gateway_class.operation_specs().items():
        if spec.untested is not None:
            continue
        for variant in spec.variants or (None,):
            uncovered.extend(
                UncoveredUnit(
                    operation=operation,
                    variant=variant,
                    capability=capability,
                )
                for capability in spec.capabilities
                if (operation, variant, capability) not in exercised
            )
    return uncovered


class FenceViolation(BaseModel):
    """One import of a fenced SDK module outside the gateway file."""

    model_config = ConfigDict(frozen=True)

    file: str
    line: int
    module: str


def gateway_fence_paths(
    gateway_class: type[SourceOperations],
) -> tuple[Path, list[Path]]:
    """Returns the gateway's own file and the directories the fence scans.

    Both derive from the gateway class itself, not from a directory-naming
    convention: ``google_site/`` (source value ``google_sites``) and ``blob/``
    (one directory serving several sources) already break name-based paths.
    """
    module_file = sys.modules[gateway_class.__module__].__file__
    assert module_file is not None, "Gateway modules always have a file."
    gateway_file = Path(module_file).resolve()
    oss_dir = gateway_file.parent
    ee_dir = Path(ee.onyx.external_permissions.__file__).parent / oss_dir.name
    return gateway_file, [oss_dir, ee_dir]


def find_import_fence_violations(
    directories: Collection[Path],
    sdk_modules: Collection[str],
    allowed_file: Path,
) -> list[FenceViolation]:
    """Finds imports of fenced SDK modules outside the gateway's own file.

    The exemption is the exact gateway file: another file that merely shares the
    ``source_operations.py`` basename (in the EE tree, or nested) is scanned
    like any other.
    """
    roots = set(sdk_modules)
    allowed = allowed_file.resolve()
    violations: list[FenceViolation] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if path.resolve() == allowed:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    # Relative imports cannot reach an external SDK.
                    if node.module is None or node.level > 0:
                        continue
                    imported = [node.module]
                else:
                    continue
                violations.extend(
                    FenceViolation(
                        file=str(path),
                        line=node.lineno,
                        module=module,
                    )
                    for module in imported
                    if module.split(".")[0] in roots
                )
    return violations
