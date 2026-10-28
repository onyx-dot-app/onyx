from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec

from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.capability_checks import (
    FILE_READ_CHECK_ID,
    SIGN_IN_CHECK_ID,
    build_azure_datalake_indexing_checks,
)
from onyx.connectors.azure_datalake.models import (
    AzureDataLakeFile,
    AzureDataLakePath,
    AzureDataLakePathPage,
    AzureDataLakeSignIn,
)
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeSourceOperations,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)

MODIFIED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _check(check_id: str) -> CapabilityCheck:
    return next(
        check
        for check in build_azure_datalake_indexing_checks()
        if check.check_id == check_id
    )


def _context(gateway: MagicMock) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.AZURE_DATALAKE,
        credential_json={},
        connector_specific_config={
            "account_name": "onyxtest",
            "container_name": "docs",
        },
        source_operations=gateway,
    )


def _file(name: str, size: int) -> AzureDataLakePath:
    return AzureDataLakePath(
        name=name, is_directory=False, last_modified=MODIFIED, content_length=size
    )


def test_an_account_key_sign_in_says_so() -> None:
    gateway = create_autospec(AzureDataLakeSourceOperations, instance=True)
    gateway.check_sign_in.return_value = AzureDataLakeSignIn(token=None)

    output = _check(SIGN_IN_CHECK_ID).run(_context(gateway))

    assert output is not None
    assert output.summary == "Signed in with the account key"


def test_the_file_check_reads_the_smallest_non_empty_file() -> None:
    gateway = create_autospec(AzureDataLakeSourceOperations, instance=True)
    gateway.list_paths_page.return_value = AzureDataLakePathPage(
        paths=[_file("big.txt", 500), _file("empty.txt", 0), _file("small.txt", 5)],
        continuation_token=None,
    )
    gateway.read_file.return_value = AzureDataLakeFile(
        size=5, last_modified=MODIFIED, content=None
    )

    output = _check(FILE_READ_CHECK_ID).run(_context(gateway))

    assert output is None
    gateway.read_file.assert_called_once_with(path="small.txt", max_bytes=0)


def test_the_file_check_says_when_there_is_nothing_to_read() -> None:
    gateway = create_autospec(AzureDataLakeSourceOperations, instance=True)
    gateway.list_paths_page.return_value = AzureDataLakePathPage(
        paths=[], continuation_token=None
    )

    output = _check(FILE_READ_CHECK_ID).run(_context(gateway))

    assert output is not None and output.advisories
    gateway.read_file.assert_not_called()
