from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from onyx.connectors.jira.connector import process_jira_issue


def test_label_skip_does_not_parse_a_malformed_description(
    create_mock_issue: Callable[..., dict[str, Any]],
) -> None:
    """An excluded ticket must be skipped before its rich text is parsed.

    Atlassian Document Format can contain ``content: null``; parsing it raises
    ``TypeError``. Before the shared-helper refactor the label check ran first,
    so such a ticket was skipped without touching the description.
    """
    issue = create_mock_issue(
        key="SKIP-1",
        labels=["skip-me"],
        description={"type": "doc", "content": None},
    )

    with patch(
        "onyx.connectors.jira.connector.rich_text",
        side_effect=AssertionError("an excluded ticket must not be parsed"),
    ):
        assert (
            process_jira_issue(
                "https://jira.example.com",
                issue,
                labels_to_skip={"skip-me"},
            )
            is None
        )
