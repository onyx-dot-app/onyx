from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ee.onyx.connectors import capability_checks as ee_capability_checks
from onyx.configs.constants import DocumentSource
from onyx.connectors import source_operations as source_operations_module
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks import registry
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from tests.unit.onyx.connectors.source_operation_harnesses import (
    compute_uncovered_units,
    find_import_fence_violations,
)


class _ScriptedCheck(CapabilityCheck):
    """Concrete check that runs an injected script against the gateway."""

    def __init__(
        self,
        capability: CredentialCapability,
        check_id: str,
        # The script receives the spy gateway; typed ``Any`` since the base
        # ``SourceOperations`` knows nothing of per-gateway operations.
        script: Callable[[Any], Any],
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name="Scripted check",
            requires_connector_instance=False,
        )
        self._script = script

    def run(self, context: CapabilityCheckContext) -> None:
        assert context.source_operations is not None, "The harness supplies a spy."
        self._script(context.source_operations)


@pytest.fixture
def gateway_class(
    monkeypatch: pytest.MonkeyPatch,
) -> type[SourceOperations]:
    """Builds an isolated synthetic gateway covering the metadata shapes."""
    monkeypatch.setattr(source_operations_module, "_SOURCE_OPERATIONS_BY_SOURCE", {})

    class _Gateway(SourceOperations):
        source = DocumentSource.SLACK
        sdk_modules = ()

        @source_operation(
            capabilities={CredentialCapability.INDEXING},
            consumes=OperationConsumes.CREDENTIAL,
            variants=("public", "private"),
        )
        def list_channels(self, *, variant: str | None = None) -> list[str]:
            return [variant] if variant else []

        @source_operation(
            capabilities={
                CredentialCapability.INDEXING,
                CredentialCapability.DOC_PERMISSION_SYNC,
            },
            consumes=OperationConsumes.CREDENTIAL,
        )
        def fetch_history(self) -> list[str]:
            return []

        @source_operation(
            capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
            consumes=OperationConsumes.NEITHER,
            untested="Dormant by design.",
        )
        def list_usergroups(self) -> list[str]:
            return []

    return _Gateway


def test_full_coverage_yields_no_uncovered_units(
    gateway_class: type[SourceOperations],
) -> None:
    """Verifies a check suite exercising every unit satisfies the harness."""
    # Precondition.
    checks = [
        _ScriptedCheck(
            CredentialCapability.INDEXING,
            "indexing_check",
            lambda operations: (
                operations.list_channels(variant="public"),
                operations.list_channels(variant="private"),
                operations.fetch_history(),
            ),
        ),
        _ScriptedCheck(
            CredentialCapability.DOC_PERMISSION_SYNC,
            "perm_sync_check",
            lambda operations: operations.fetch_history(),
        ),
    ]

    # Under test and postcondition.
    # ``list_usergroups`` is untested-exempt, so nothing is uncovered.
    assert compute_uncovered_units(gateway_class, checks) == []


def test_missing_variant_is_reported(
    gateway_class: type[SourceOperations],
) -> None:
    """Verifies coverage is counted per variant, not per operation."""
    # Precondition.
    checks = [
        _ScriptedCheck(
            CredentialCapability.INDEXING,
            "indexing_check",
            lambda operations: (
                operations.list_channels(variant="public"),
                operations.fetch_history(),
            ),
        ),
        _ScriptedCheck(
            CredentialCapability.DOC_PERMISSION_SYNC,
            "perm_sync_check",
            lambda operations: operations.fetch_history(),
        ),
    ]

    # Under test.
    uncovered = compute_uncovered_units(gateway_class, checks)

    # Postcondition.
    assert [(unit.operation, unit.variant, unit.capability) for unit in uncovered] == [
        ("list_channels", "private", CredentialCapability.INDEXING)
    ]


def test_coverage_is_attributed_per_capability_tag(
    gateway_class: type[SourceOperations],
) -> None:
    """
    Verifies an operation serving two capabilities needs a check of each: an
    INDEXING-only suite leaves the DOC_PERMISSION_SYNC tag uncovered.
    """
    # Precondition.
    checks = [
        _ScriptedCheck(
            CredentialCapability.INDEXING,
            "indexing_check",
            lambda operations: (
                operations.list_channels(variant="public"),
                operations.list_channels(variant="private"),
                operations.fetch_history(),
            ),
        ),
    ]

    # Under test.
    uncovered = compute_uncovered_units(gateway_class, checks)

    # Postcondition.
    assert [(unit.operation, unit.capability) for unit in uncovered] == [
        ("fetch_history", CredentialCapability.DOC_PERMISSION_SYNC)
    ]


def test_raising_check_still_counts_its_calls(
    gateway_class: type[SourceOperations],
) -> None:
    """Verifies calls recorded before a check fails on mock data still count."""

    # Precondition.
    def failing_script(operations: Any) -> None:
        operations.list_channels(variant="public")
        operations.list_channels(variant="private")
        operations.fetch_history()
        raise RuntimeError("Mock data never satisfies the probe.")

    checks = [
        _ScriptedCheck(CredentialCapability.INDEXING, "indexing_check", failing_script),
        _ScriptedCheck(
            CredentialCapability.DOC_PERMISSION_SYNC,
            "perm_sync_check",
            lambda operations: operations.fetch_history(),
        ),
    ]

    # Under test and postcondition.
    assert compute_uncovered_units(gateway_class, checks) == []


def test_mis_shaped_calls_do_not_count_as_coverage(
    gateway_class: type[SourceOperations],
) -> None:
    """
    Verifies the spy enforces real operation signatures: a call the real gateway
    would reject records nothing and cannot certify coverage.
    """

    # Precondition.
    # ``fetch_history`` takes no arguments beyond ``self``; the indexing check
    # calls it with one, which the autospecced spy rejects unrecorded.
    def mis_shaped_script(operations: Any) -> None:
        operations.list_channels(variant="public")
        operations.list_channels(variant="private")
        operations.fetch_history("argument_the_operation_does_not_take")

    checks = [
        _ScriptedCheck(
            CredentialCapability.INDEXING, "indexing_check", mis_shaped_script
        ),
        _ScriptedCheck(
            CredentialCapability.DOC_PERMISSION_SYNC,
            "perm_sync_check",
            lambda operations: operations.fetch_history(),
        ),
    ]

    # Under test.
    uncovered = compute_uncovered_units(gateway_class, checks)

    # Postcondition.
    assert [(unit.operation, unit.capability) for unit in uncovered] == [
        ("fetch_history", CredentialCapability.INDEXING)
    ]


@pytest.mark.usefixtures("enable_ee")
def test_coverage_pipeline_sees_ee_perm_sync_checks(
    gateway_class: type[SourceOperations],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verifies the real check-fetch path resolves EE checks under ``enable_ee``:
    perm-sync-tagged units are coverable only by EE-registered checks, so a
    coverage run without EE resolution would report them uncovered.
    """
    # Precondition.
    monkeypatch.setitem(
        registry._INDEXING_CHECKS_BY_SOURCE,
        gateway_class.source,
        [
            _ScriptedCheck(
                CredentialCapability.INDEXING,
                "indexing_check",
                lambda operations: (
                    operations.list_channels(variant="public"),
                    operations.list_channels(variant="private"),
                    operations.fetch_history(),
                ),
            )
        ],
    )
    monkeypatch.setitem(
        ee_capability_checks._DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE,
        gateway_class.source,
        [
            _ScriptedCheck(
                CredentialCapability.DOC_PERMISSION_SYNC,
                "perm_sync_check",
                lambda operations: operations.fetch_history(),
            )
        ],
    )

    # Under test.
    checks = get_capability_checks(gateway_class.source)

    # Postcondition.
    assert compute_uncovered_units(gateway_class, checks) == []


def test_fence_finder_flags_imports_outside_the_gateway(tmp_path: Path) -> None:
    """Verifies SDK imports are flagged everywhere except the gateway file."""
    # Precondition.
    gateway_file = tmp_path / "source_operations.py"
    gateway_file.write_text("import slack_sdk\nfrom slack_sdk.web import WebClient\n")
    (tmp_path / "utils.py").write_text(
        "import json\nfrom slack_sdk.web import WebClient\n"
    )
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "helpers.py").write_text("import slack_sdk.errors\n")
    (tmp_path / "clean.py").write_text("from . import utils\nimport requests\n")

    # Under test.
    violations = find_import_fence_violations(
        [tmp_path], ("slack_sdk",), allowed_file=gateway_file
    )

    # Postcondition.
    assert [
        (Path(violation.file).name, violation.line, violation.module)
        for violation in violations
    ] == [
        ("helpers.py", 1, "slack_sdk.errors"),
        ("utils.py", 2, "slack_sdk.web"),
    ]


def test_fence_exempts_the_exact_gateway_file_not_its_basename(
    tmp_path: Path,
) -> None:
    """
    Verifies a file merely sharing the gateway basename (in the EE tree or
    nested) is scanned like any other.
    """
    # Precondition.
    oss_dir = tmp_path / "oss"
    ee_dir = tmp_path / "ee"
    oss_dir.mkdir()
    ee_dir.mkdir()
    gateway_file = oss_dir / "source_operations.py"
    gateway_file.write_text("import slack_sdk\n")
    (ee_dir / "source_operations.py").write_text("import slack_sdk\n")

    # Under test.
    violations = find_import_fence_violations(
        [oss_dir, ee_dir], ("slack_sdk",), allowed_file=gateway_file
    )

    # Postcondition.
    assert [
        (Path(violation.file).parent.name, violation.module) for violation in violations
    ] == [("ee", "slack_sdk")]


def test_fence_finder_ignores_missing_directories(tmp_path: Path) -> None:
    """Verifies sources without an EE perm-sync directory scan cleanly."""
    # Under test and postcondition.
    assert (
        find_import_fence_violations(
            [Path("/nonexistent/for/sure")],
            ("slack_sdk",),
            allowed_file=tmp_path / "source_operations.py",
        )
        == []
    )
