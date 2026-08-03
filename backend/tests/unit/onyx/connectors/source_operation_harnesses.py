"""Reusable logic behind the auto-discovering source-operations harnesses.

The harness tests (coverage and import fence) parametrize over
``registered_source_operations()``; the functions here do the actual work so
they can be unit-tested against synthetic gateways and directories.
"""

import ast
import importlib
from collections.abc import Collection, Sequence
from pathlib import Path
from unittest.mock import MagicMock

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

    Asserts every discovered module registered a gateway for its directory's
    source, so discovery rot (a rename, a glob mismatch) surfaces as a loud
    collection error instead of vacuously skipped harnesses.
    """
    connectors_dir = Path(onyx.connectors.__file__).parent
    for path in sorted(connectors_dir.glob("*/source_operations.py")):
        source_value = path.parent.name
        importlib.import_module(f"onyx.connectors.{source_value}.source_operations")
        registered = {source.value for source in registered_source_operations()}
        assert source_value in registered, (
            f"{path} was imported but registered no gateway for "
            f"{source_value!r}; the coverage and fence harnesses would "
            "silently skip it."
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
    against mock data and may raise; their calls are recorded regardless.
    """
    exercised: set[tuple[str, str | None, CredentialCapability]] = set()
    for check in checks:
        spy = MagicMock(spec=gateway_class)
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
            operation = name.split(".")[0]
            if not operation:
                continue
            exercised.add((operation, kwargs.get("variant"), check.capability))

    uncovered: list[UncoveredUnit] = []
    for operation, spec in gateway_class.operation_specs().items():
        if spec.untested is not None:
            continue
        for variant in spec.variants or (None,):
            for capability in spec.capabilities:
                if (operation, variant, capability) not in exercised:
                    uncovered.append(
                        UncoveredUnit(
                            operation=operation,
                            variant=variant,
                            capability=capability,
                        )
                    )
    return uncovered


class FenceViolation(BaseModel):
    """One import of a fenced SDK module outside the gateway file."""

    model_config = ConfigDict(frozen=True)

    file: str
    line: int
    module: str


def fence_directories_for_source(source_value: str) -> list[Path]:
    """Returns the directories the import fence scans for a source."""
    return [
        Path(onyx.connectors.__file__).parent / source_value,
        Path(ee.onyx.external_permissions.__file__).parent / source_value,
    ]


def find_import_fence_violations(
    directories: Collection[Path],
    sdk_modules: Collection[str],
    allowed_filename: str = "source_operations.py",
) -> list[FenceViolation]:
    """Finds imports of fenced SDK modules outside the gateway file."""
    roots = set(sdk_modules)
    violations: list[FenceViolation] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if path.name == allowed_filename:
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
                for module in imported:
                    if module.split(".")[0] in roots:
                        violations.append(
                            FenceViolation(
                                file=str(path),
                                line=node.lineno,
                                module=module,
                            )
                        )
    return violations
