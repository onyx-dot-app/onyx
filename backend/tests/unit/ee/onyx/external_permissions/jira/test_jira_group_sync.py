import logging
from unittest.mock import create_autospec

import pytest

from ee.onyx.external_permissions.jira.group_sync import (
    _fetch_group_member_page,
    _get_group_member_emails,
)
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations


def test_get_group_member_emails_skips_deleted_group(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway.get_group_members_page.side_effect = JiraApiError(
        "error",
        status_code=404,
        text=(
            '{"errorMessages":["The group named \'stale group \' does not '
            'exist"],"errors":{}}'
        ),
    )

    with caplog.at_level(logging.WARNING):
        member_emails = _get_group_member_emails(gateway, "stale group ")

    assert member_emails == set()
    assert "no longer exists" in caplog.text


def test_fetch_group_member_page_keeps_unrecognized_404_error() -> None:
    gateway = create_autospec(JiraSourceOperations, instance=True)
    gateway.get_group_members_page.side_effect = JiraApiError(
        "error",
        status_code=404,
        text="Not Found",
    )

    with pytest.raises(RuntimeError, match="requires Jira 6.0"):
        _fetch_group_member_page(gateway, "jira-users", 0)
