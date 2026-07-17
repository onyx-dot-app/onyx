import logging
from unittest.mock import MagicMock

import pytest
from jira import JIRA
from jira.exceptions import JIRAError

from ee.onyx.external_permissions.jira.group_sync import _fetch_group_member_page
from ee.onyx.external_permissions.jira.group_sync import _get_group_member_emails


def test_get_group_member_emails_skips_deleted_group(
    caplog: pytest.LogCaptureFixture,
) -> None:
    jira_client = MagicMock(spec=JIRA)
    jira_client._get_json.side_effect = JIRAError(
        status_code=404,
        text=(
            '{"errorMessages":["The group named \'stale group \' does not '
            'exist"],"errors":{}}'
        ),
    )

    with caplog.at_level(logging.WARNING):
        member_emails = _get_group_member_emails(jira_client, "stale group ")

    assert member_emails == set()
    assert "no longer exists" in caplog.text


def test_fetch_group_member_page_keeps_unrecognized_404_error() -> None:
    jira_client = MagicMock(spec=JIRA)
    jira_client._get_json.side_effect = JIRAError(
        status_code=404,
        text="Not Found",
    )

    with pytest.raises(RuntimeError, match="requires Jira 6.0"):
        _fetch_group_member_page(jira_client, "jira-users", 0)
