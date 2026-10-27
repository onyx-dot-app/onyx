from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

from ee.onyx.external_permissions.google_drive.permission_retrieval import (
    get_permissions_by_ids,
)
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)


def test_a_denied_later_page_keeps_the_permissions_already_read() -> None:
    def pages(**_kwargs: Any) -> Iterator[dict[str, Any]]:
        yield {"id": "p1", "type": "user", "emailAddress": "a@example.com"}
        raise GoogleDriveHttpError(
            status_code=403, reasons=(), access_denied=True, message="denied"
        )

    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.list_file_permissions.side_effect = pages

    permissions = get_permissions_by_ids(
        ops=ops, user_email="a@example.com", doc_id="doc", permission_ids=["p1", "p2"]
    )

    assert [permission.id for permission in permissions] == ["p1"]
