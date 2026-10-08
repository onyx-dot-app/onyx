from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.config_diff import (
    build_source_scoped_backfill_config,
    classify_source_config_change,
)
from onyx.connectors.field_policy import ScopeDirection
from onyx.connectors.github.config import GithubConnectorConfig
from onyx.connectors.planning_rule_registry import PLANNING_RULES
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.testrail import config as testrail_config

_CONFLUENCE_SITE = {"wiki_base": "https://example.atlassian.net", "is_cloud": True}
_BITBUCKET_WORKSPACE = {"workspace": "onyx"}
_DRUPAL_SITE = {"base_url": "https://wiki.example.com"}
_ASANA_WORKSPACE = {"asana_workspace_id": "w"}
_JIRA_SITE = {"jira_base_url": "https://example.atlassian.net"}


def test_every_rule_reads_the_config_class_of_its_source() -> None:
    for source, rule in PLANNING_RULES.items():
        assert rule.config_class is CONNECTOR_CLASS_MAP[source].config_class, source


@pytest.mark.parametrize(
    "source, old, new, expected",
    [
        # Slack
        (
            DocumentSource.SLACK,
            {"include_bot_messages": False},
            {"include_bot_messages": True},
            {"include_bot_messages": ScopeDirection.WIDEN},
        ),
        (
            DocumentSource.SLACK,
            {"include_bot_messages": True},
            {"include_bot_messages": False},
            {"include_bot_messages": ScopeDirection.BOTH},
        ),
        (
            DocumentSource.SLACK,
            {"channels": ["general"]},
            {"channels": ["gen.*"], "channel_regex_enabled": True},
            {
                "channels": ScopeDirection.UNKNOWN,
                "channel_regex_enabled": ScopeDirection.UNKNOWN,
            },
        ),
        # Confluence
        (
            DocumentSource.CONFLUENCE,
            _CONFLUENCE_SITE,
            _CONFLUENCE_SITE | {"space": "A"},
            {"space": ScopeDirection.NARROW},
        ),
        (
            DocumentSource.CONFLUENCE,
            _CONFLUENCE_SITE | {"space": "A"},
            _CONFLUENCE_SITE | {"space": "A", "page_id": "1"},
            {"page_id": ScopeDirection.UNKNOWN},
        ),
        (
            DocumentSource.CONFLUENCE,
            _CONFLUENCE_SITE | {"page_id": "1"},
            _CONFLUENCE_SITE | {"page_id": "1", "index_recursively": True},
            {"index_recursively": ScopeDirection.WIDEN},
        ),
        # A space change has no effect while a CQL query is set.
        (
            DocumentSource.CONFLUENCE,
            _CONFLUENCE_SITE | {"cql_query": "a", "space": "X"},
            _CONFLUENCE_SITE | {"cql_query": "a", "space": "Y"},
            {},
        ),
        (
            DocumentSource.CONFLUENCE,
            _CONFLUENCE_SITE | {"labels_to_skip": ["a"]},
            _CONFLUENCE_SITE | {"labels_to_skip": ["a", "b"]},
            {"labels_to_skip": ScopeDirection.BOTH},
        ),
        (
            DocumentSource.CONFLUENCE,
            _CONFLUENCE_SITE | {"labels_to_skip": ["a", "b"]},
            _CONFLUENCE_SITE | {"labels_to_skip": ["a"]},
            {"labels_to_skip": ScopeDirection.WIDEN},
        ),
        # Google Drive
        (
            DocumentSource.GOOGLE_DRIVE,
            {"include_shared_drives": True},
            {"shared_drive_urls": "u"},
            {
                "include_shared_drives": ScopeDirection.UNKNOWN,
                "shared_drive_urls": ScopeDirection.UNKNOWN,
            },
        ),
        (
            DocumentSource.GOOGLE_DRIVE,
            {"shared_drive_urls": "u"},
            {"shared_drive_urls": "u", "include_my_drives": True},
            {},
        ),
        (
            DocumentSource.GOOGLE_DRIVE,
            {"include_shared_drives": True},
            {"include_shared_drives": True, "include_my_drives": True},
            {"include_my_drives": ScopeDirection.WIDEN},
        ),
        # Bitbucket
        (
            DocumentSource.BITBUCKET,
            _BITBUCKET_WORKSPACE | {"repositories": "a", "projects": "p"},
            _BITBUCKET_WORKSPACE | {"repositories": "a", "projects": "q"},
            {},
        ),
        (
            DocumentSource.BITBUCKET,
            _BITBUCKET_WORKSPACE | {"repositories": "a", "projects": "p"},
            _BITBUCKET_WORKSPACE | {"projects": "p"},
            {"repositories": ScopeDirection.UNKNOWN},
        ),
        (
            DocumentSource.BITBUCKET,
            _BITBUCKET_WORKSPACE | {"repositories": "a"},
            _BITBUCKET_WORKSPACE | {"repositories": "a,b"},
            {"repositories": ScopeDirection.WIDEN},
        ),
        # Teams
        (
            DocumentSource.TEAMS,
            {"meeting_organizers": ["a"], "transcript_organizers": ["x"]},
            {"meeting_organizers": ["a", "b"], "transcript_organizers": ["x"]},
            {"meeting_organizers": ScopeDirection.UNKNOWN},
        ),
        (
            DocumentSource.TEAMS,
            {"meeting_organizers": ["a"]},
            {"meeting_organizers": ["a", "b"]},
            {"meeting_organizers": ScopeDirection.WIDEN},
        ),
        # Outlook
        (
            DocumentSource.OUTLOOK,
            {"include_calendar": True},
            {"include_calendar": True, "calendar_past_days": 400},
            {"calendar_past_days": ScopeDirection.WIDEN},
        ),
        (
            DocumentSource.OUTLOOK,
            {"include_calendar": True},
            {"include_calendar": True, "calendar_future_days": 10},
            {"calendar_future_days": ScopeDirection.NARROW},
        ),
        (DocumentSource.OUTLOOK, {}, {"calendar_past_days": 400}, {}),
        # Outlook walks the listed mailboxes plus the members of the listed
        # groups, and every mailbox when neither is listed.
        (
            DocumentSource.OUTLOOK,
            {},
            {"mailbox_groups": ["Sales"]},
            {"mailbox_groups": ScopeDirection.NARROW},
        ),
        (
            DocumentSource.OUTLOOK,
            {"mailboxes": ["a@example.com"]},
            {"mailboxes": ["a@example.com"], "mailbox_groups": ["Sales"]},
            {"mailbox_groups": ScopeDirection.WIDEN},
        ),
        (
            DocumentSource.OUTLOOK,
            {"mailboxes": ["a@example.com"]},
            {"mailbox_groups": ["Sales"]},
            {
                "mailboxes": ScopeDirection.BOTH,
                "mailbox_groups": ScopeDirection.BOTH,
            },
        ),
        (
            DocumentSource.OUTLOOK,
            {"mailbox_groups": ["Sales"]},
            {"mailbox_groups": []},
            {"mailbox_groups": ScopeDirection.WIDEN},
        ),
        (
            DocumentSource.OUTLOOK,
            {"mailboxes": ["A@example.com"]},
            {"mailboxes": [" a@example.com"]},
            {},
        ),
        # Salesforce
        (
            DocumentSource.SALESFORCE,
            {"requested_objects": ["Account"]},
            {"requested_objects": ["Account", "Contact"]},
            {"requested_objects": ScopeDirection.WIDEN},
        ),
        (
            DocumentSource.SALESFORCE,
            {"requested_objects": ["Account"]},
            {"requested_objects": ["account"]},
            {},
        ),
        (
            DocumentSource.SALESFORCE,
            {"custom_query_config": "{}"},
            {"custom_query_config": "{}", "requested_objects": ["X"]},
            {},
        ),
        (
            DocumentSource.SALESFORCE,
            {},
            {"custom_query_config": "{}", "requested_objects": ["X"]},
            {
                "requested_objects": ScopeDirection.UNKNOWN,
                "custom_query_config": ScopeDirection.UNKNOWN,
            },
        ),
        # Zoom
        (
            DocumentSource.ZOOM,
            {},
            {"include_meetings": False},
            {"include_meetings": ScopeDirection.NARROW},
        ),
        (
            DocumentSource.ZOOM,
            {"include_meetings": None},
            {"include_meetings": True},
            {},
        ),
        (
            DocumentSource.ZOOM,
            {"include_webinars": False},
            {},
            {"include_webinars": ScopeDirection.WIDEN},
        ),
        # Drupal Wiki
        (
            DocumentSource.DRUPAL_WIKI,
            _DRUPAL_SITE,
            _DRUPAL_SITE | {"spaces": ["1"]},
            {"spaces": ScopeDirection.NARROW},
        ),
        (
            DocumentSource.DRUPAL_WIKI,
            _DRUPAL_SITE | {"spaces": ["1"], "pages": ["p"]},
            _DRUPAL_SITE | {"pages": ["p"]},
            {"spaces": ScopeDirection.NARROW},
        ),
        (
            DocumentSource.DRUPAL_WIKI,
            _DRUPAL_SITE | {"pages": ["p"]},
            _DRUPAL_SITE | {"spaces": ["1"]},
            {"spaces": ScopeDirection.WIDEN, "pages": ScopeDirection.NARROW},
        ),
        # Asana: the team filter applies only without project ids.
        (
            DocumentSource.ASANA,
            _ASANA_WORKSPACE | {"asana_project_ids": "1", "asana_team_id": "a"},
            _ASANA_WORKSPACE | {"asana_project_ids": "1", "asana_team_id": "b"},
            {},
        ),
        (
            DocumentSource.ASANA,
            _ASANA_WORKSPACE | {"asana_team_id": "a"},
            _ASANA_WORKSPACE | {"asana_team_id": "b"},
            {"asana_team_id": ScopeDirection.BOTH},
        ),
        # Jira: a JQL query replaces the project key.
        (
            DocumentSource.JIRA,
            _JIRA_SITE | {"jql_query": "q", "project_key": "A"},
            _JIRA_SITE | {"jql_query": "q", "project_key": "B"},
            {},
        ),
        (
            DocumentSource.JIRA,
            _JIRA_SITE | {"project_key": "A"},
            _JIRA_SITE | {"project_key": "B"},
            {"project_key": ScopeDirection.BOTH},
        ),
        # ClickUp: a workspace connector sends no container filter.
        (
            DocumentSource.CLICKUP,
            {"connector_ids": ["1"]},
            {"connector_ids": ["2"]},
            {},
        ),
        (
            DocumentSource.CLICKUP,
            {"connector_type": "list", "connector_ids": ["1"]},
            {"connector_type": "list", "connector_ids": ["1", "2"]},
            {"connector_ids": ScopeDirection.WIDEN},
        ),
        # Notion: a root page is always followed recursively.
        (
            DocumentSource.NOTION,
            {"root_page_id": "r", "recursive_index_enabled": False},
            {"root_page_id": "r", "recursive_index_enabled": True},
            {},
        ),
        (
            DocumentSource.NOTION,
            {"recursive_index_enabled": False},
            {"recursive_index_enabled": True},
            {"recursive_index_enabled": ScopeDirection.WIDEN},
        ),
        # Outlook matches excluded folder names without case.
        (
            DocumentSource.OUTLOOK,
            {"excluded_folders": ["Inbox"]},
            {"excluded_folders": ["inbox "]},
            {},
        ),
        (
            DocumentSource.OUTLOOK,
            {"excluded_folders": ["Inbox"]},
            {"excluded_folders": ["inbox", "Sent"]},
            {"excluded_folders": ScopeDirection.NARROW},
        ),
        # Two unbounded values are the same scope.
        (DocumentSource.DISCORD, {"start_date": None}, {"start_date": ""}, {}),
        # TestRail: 0 and blank are the default limit, and only None or a
        # blank string fetches every project.
        (
            DocumentSource.TESTRAIL,
            {"max_pages": 100},
            {"max_pages": 0},
            {"max_pages": ScopeDirection.WIDEN},
        ),
        (DocumentSource.TESTRAIL, {"skip_doc_absolute_chars": ""}, {}, {}),
        (
            DocumentSource.TESTRAIL,
            {"cases_page_size": 100},
            {"cases_page_size": 50},
            {"cases_page_size": ScopeDirection.UNKNOWN},
        ),
        (
            DocumentSource.TESTRAIL,
            {"project_ids": ""},
            {"project_ids": []},
            {"project_ids": ScopeDirection.NARROW},
        ),
        (
            DocumentSource.TESTRAIL,
            {"project_ids": []},
            {"project_ids": "1"},
            {"project_ids": ScopeDirection.WIDEN},
        ),
        # HubSpot: None fetches every type, [] none.
        (
            DocumentSource.HUBSPOT,
            {},
            {"object_types": []},
            {"object_types": ScopeDirection.NARROW},
        ),
        (
            DocumentSource.HUBSPOT,
            {"object_types": []},
            {"object_types": ["tickets"]},
            {"object_types": ScopeDirection.WIDEN},
        ),
        # Xenforo: the crawled URL is not part of document ids.
        (
            DocumentSource.XENFORO,
            {"base_url": "https://a.example.com/threads/1/"},
            {"base_url": "https://a.example.com/threads/2/"},
            {"base_url": ScopeDirection.UNKNOWN},
        ),
    ],
)
def test_source_rule_directions(
    source: DocumentSource,
    old: dict[str, Any],
    new: dict[str, Any],
    expected: dict[str, ScopeDirection],
) -> None:
    changes = classify_source_config_change(source, old, new)

    assert {change.field_name: change.scope_direction for change in changes} == (
        expected
    )


@pytest.mark.parametrize(
    "raw, expected",
    [(None, None), ("", None), ("  ", None), (" main ", "main")],
)
def test_github_branch_and_repositories_are_stripped(
    raw: str | None, expected: str | None
) -> None:
    config = GithubConnectorConfig.model_validate(
        {"repo_owner": "onyx", "repositories": raw, "branch": raw}
    )

    assert config.repositories == expected
    assert config.branch == expected


def test_github_whitespace_is_not_a_change() -> None:
    assert (
        classify_source_config_change(
            DocumentSource.GITHUB,
            {"repo_owner": "onyx", "repositories": "a", "branch": "main"},
            {"repo_owner": "onyx", "repositories": " a ", "branch": " main "},
        )
        == []
    )


def test_github_scoped_backfill_for_added_repositories() -> None:
    delta = build_source_scoped_backfill_config(
        DocumentSource.GITHUB,
        {"repo_owner": "onyx", "repositories": "a", "include_issues": True},
        {"repo_owner": "onyx", "repositories": "a,b", "include_issues": True},
    )

    assert delta == {"repo_owner": "onyx", "repositories": "b", "include_issues": True}


def test_salesforce_scoped_backfill_holds_only_added_types() -> None:
    # {} resolves to Account, so only Contact is new.
    delta = build_source_scoped_backfill_config(
        DocumentSource.SALESFORCE, {}, {"requested_objects": ["Account", "Contact"]}
    )

    assert delta == {"requested_objects": ["Contact"]}


def test_testrail_zero_and_blank_limits_are_none() -> None:
    config = testrail_config.TestRailConnectorConfig.model_validate(
        {"max_pages": 0, "skip_doc_absolute_chars": "", "cases_page_size": 0}
    )

    assert config.max_pages is None
    assert config.skip_doc_absolute_chars is None
    assert config.cases_page_size is None


def test_rule_direction_blocks_scoped_backfill() -> None:
    # The default rules would widen meeting_organizers by one item.
    assert (
        build_source_scoped_backfill_config(
            DocumentSource.TEAMS,
            {"meeting_organizers": ["a"], "transcript_organizers": ["x"]},
            {"meeting_organizers": ["a", "b"], "transcript_organizers": ["x"]},
        )
        is None
    )
