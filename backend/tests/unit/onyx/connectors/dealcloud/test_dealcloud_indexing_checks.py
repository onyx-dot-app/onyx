from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
)
from onyx.connectors.dealcloud.capability_checks import (
    build_dealcloud_indexing_checks,
)
from onyx.connectors.dealcloud.models import DealCloudEntryType
from onyx.connectors.dealcloud.source_operations import DealCloudSourceOperations
from onyx.connectors.exceptions import (
    InconclusiveValidationError,
    NothingToCheckError,
    UnexpectedValidationError,
)


def _entries_check() -> CapabilityCheck:
    return next(
        check
        for check in build_dealcloud_indexing_checks()
        if check.check_id == "dealcloud_entries"
    )


def _run(ops: MagicMock) -> CheckOutput | None:
    return _entries_check().run(
        CapabilityCheckContext(
            source=DocumentSource.DEALCLOUD,
            credential_json={},
            connector_specific_config={
                "base_url": "https://example.dealcloud.com",
                "entry_types": ["Company"],
            },
            source_operations=ops,
        )
    )


def _ops(entry_ids: list[int]) -> MagicMock:
    ops = create_autospec(DealCloudSourceOperations, instance=True)
    ops.list_entry_types.return_value = [
        DealCloudEntryType(
            id=2014, api_name="Company", plural_name="Companies", entry_list_type=1
        )
    ]
    ops.list_entry_ids.return_value = entry_ids
    return ops


def test_reading_an_entrys_row_passes_without_advisory() -> None:
    ops = _ops([7, 9])

    assert _run(ops) is None
    ops.get_rows.assert_called_once_with(entry_type_id=2014, entry_ids=[7])


def test_a_listed_entry_without_a_row_fails() -> None:
    ops = _ops([7])
    ops.get_rows.return_value = []

    with pytest.raises(UnexpectedValidationError, match="returned no row"):
        _run(ops)


def test_a_scope_without_entries_has_nothing_to_check() -> None:
    ops = _ops([])

    with pytest.raises(NothingToCheckError):
        _run(ops)
    ops.get_rows.assert_not_called()


def test_a_sample_without_entries_from_a_larger_scope_is_inconclusive() -> None:
    ops = _ops([])
    ops.list_entry_types.return_value = [
        DealCloudEntryType(
            id=n, api_name=f"Object{n}", plural_name=f"Objects {n}", entry_list_type=1
        )
        for n in range(6)
    ]

    with pytest.raises(InconclusiveValidationError, match="first 5 objects"):
        _entries_check().run(
            CapabilityCheckContext(
                source=DocumentSource.DEALCLOUD,
                credential_json={},
                connector_specific_config={"base_url": "https://example.dealcloud.com"},
                source_operations=ops,
            )
        )
    assert ops.list_entry_ids.call_count == 5


def test_the_sign_in_check_fails_when_dealcloud_is_unreachable() -> None:
    sign_in = next(
        check
        for check in build_dealcloud_indexing_checks()
        if check.check_id == "dealcloud_sign_in"
    )

    assert sign_in.fails_when_unreachable is True
    assert sign_in.validates_binding is True
