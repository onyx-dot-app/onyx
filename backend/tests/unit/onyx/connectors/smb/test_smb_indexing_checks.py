from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.smb.capability_checks import (
    FILE_READ_CHECK_ID,
    PATH_PREFIX_CHECK_ID,
    SHARE_CHECK_ID,
    SIGN_IN_CHECK_ID,
    TRANSPORT_CHECK_ID,
    build_smb_indexing_checks,
)
from onyx.connectors.smb.models import (
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_REPARSE_POINT,
    SmbEntry,
    SmbSessionInfo,
)
from onyx.connectors.smb.source_operations import (
    SmbAccessDeniedError,
    SmbSourceOperations,
)

CHANGED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _check(check_id: str) -> CapabilityCheck:
    return next(
        check for check in build_smb_indexing_checks() if check.check_id == check_id
    )


def _context(gateway: MagicMock, path_prefix: str = "") -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.SMB,
        credential_json={
            "smb_domain": "CORP",
            "smb_username": "svc-onyx",
            "smb_password": "secret",
        },
        connector_specific_config={
            "host": "fs01",
            "share": "Plans",
            "path_prefix": path_prefix,
        },
        source_operations=gateway,
    )


def _entry(name: str, size: int = 0, attributes: int = 0) -> SmbEntry:
    return SmbEntry(
        name=name,
        attributes=attributes,
        creation_time=CHANGED,
        last_write_time=CHANGED,
        change_time=CHANGED,
        size=size,
    )


def _gateway() -> MagicMock:
    return create_autospec(SmbSourceOperations, instance=True)


def test_sign_in_names_the_account_and_never_the_password() -> None:
    output = _check(SIGN_IN_CHECK_ID).run(_context(_gateway()))

    assert isinstance(output, CheckOutput)
    assert output.summary == "Signed in as CORP\\svc-onyx"


def test_transport_reports_encryption_and_warns_without_it() -> None:
    gateway = _gateway()
    gateway.connect.return_value = SmbSessionInfo(
        dialect="3.1.1", signing_required=True, encrypted=True
    )
    encrypted = _check(TRANSPORT_CHECK_ID).run(_context(gateway))
    gateway.connect.return_value = SmbSessionInfo(
        dialect="2.1", signing_required=True, encrypted=False
    )
    signed = _check(TRANSPORT_CHECK_ID).run(_context(gateway))
    gateway.connect.return_value = SmbSessionInfo(
        dialect="2.1", signing_required=False, encrypted=False
    )

    assert isinstance(encrypted, CheckOutput) and isinstance(signed, CheckOutput)
    assert encrypted.summary == "SMB 3.1.1, encrypted" and not encrypted.advisories
    assert signed.summary == "SMB 2.1, signed" and len(signed.advisories) == 1
    with pytest.raises(ConnectorValidationError):
        _check(TRANSPORT_CHECK_ID).run(_context(gateway))


def test_an_unreadable_share_root_passes_only_with_a_path_prefix() -> None:
    gateway = _gateway()
    gateway.list_folder.side_effect = SmbAccessDeniedError("denied")

    output = _check(SHARE_CHECK_ID).run(_context(gateway, path_prefix="Projects"))

    assert isinstance(output, CheckOutput) and len(output.advisories) == 1
    with pytest.raises(SmbAccessDeniedError):
        _check(SHARE_CHECK_ID).run(_context(gateway))


@pytest.mark.parametrize(
    "attributes, accepted",
    [
        (FILE_ATTRIBUTE_DIRECTORY, True),
        (0, False),
        (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT, False),
    ],
)
def test_path_prefix_must_be_a_real_folder(attributes: int, accepted: bool) -> None:
    gateway = _gateway()
    gateway.stat.return_value = _entry("Projects", attributes=attributes)
    gateway.list_folder.return_value = []
    context = _context(gateway, path_prefix="Projects")

    if accepted:
        _check(PATH_PREFIX_CHECK_ID).run(context)
        return
    with pytest.raises(ConnectorValidationError):
        _check(PATH_PREFIX_CHECK_ID).run(context)


def test_file_read_opens_the_smallest_file_indexing_admits() -> None:
    gateway = _gateway()
    listings: dict[str, list[SmbEntry]] = {
        "": [
            _entry("Projects", attributes=FILE_ATTRIBUTE_DIRECTORY),
            _entry("drawing.dwg", size=1),
            _entry("~$lock.docx", size=1),
            _entry("empty.txt", size=0),
        ],
        "Projects": [_entry("big.txt", size=500), _entry("small.txt", size=5)],
    }
    gateway.list_folder.side_effect = lambda *, path: listings[path]

    output = _check(FILE_READ_CHECK_ID).run(_context(gateway))

    assert output is None
    gateway.read_file.assert_called_once_with(path="Projects/small.txt", max_bytes=0)


def test_file_read_says_when_there_was_nothing_to_read() -> None:
    gateway = _gateway()
    gateway.list_folder.return_value = []

    output = _check(FILE_READ_CHECK_ID).run(_context(gateway))

    assert isinstance(output, CheckOutput) and len(output.advisories) == 1
    gateway.read_file.assert_not_called()
