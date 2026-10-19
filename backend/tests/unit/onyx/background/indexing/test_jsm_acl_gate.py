"""Incremental JSM full indexing must not omit ACLs after a prior sync."""

from unittest.mock import patch

import pytest

from onyx.background.indexing.run_docfetching import (
    _should_fetch_permissions_for_index_attempt,
)
from onyx.configs.constants import DocumentSource


@pytest.mark.parametrize(
    "source,perm_synced,primary,first_run,success_before,expected",
    [
        (DocumentSource.JIRA_SERVICE_MANAGEMENT, True, True, False, True, True),
        (DocumentSource.JIRA_SERVICE_MANAGEMENT, True, False, False, True, True),
        (DocumentSource.JIRA_SERVICE_MANAGEMENT, True, True, True, False, True),
        (DocumentSource.JIRA_SERVICE_MANAGEMENT, False, True, True, False, False),
        (DocumentSource.JIRA, True, True, False, True, False),
        (DocumentSource.JIRA, True, True, True, False, True),
        (DocumentSource.JIRA, True, False, True, False, False),
    ],
)
def test_permission_index_gate(
    source: DocumentSource,
    perm_synced: bool,
    primary: bool,
    first_run: bool,
    success_before: bool,
    expected: bool,
) -> None:
    with patch(
        "onyx.background.indexing.run_docfetching."
        "source_should_fetch_permissions_during_indexing",
        return_value=True,
    ):
        result = _should_fetch_permissions_for_index_attempt(
            source=source,
            is_perm_synced=perm_synced,
            is_primary=primary,
            from_beginning=first_run,
            has_successful_attempt=success_before,
        )
    assert result == expected
