"""The config models' field format rules reach the create form as the plan's
``form_errors``, keyed by field, with the design's line as the message. A
stored config that breaks a rule still indexes as before."""

import re
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.config import (
    CQL_LAST_MODIFIED_ERROR,
    CQL_ORDER_BY_ERROR,
    PAGE_ID_FORMAT_ERROR,
)
from onyx.connectors.factory import build_connector_kwargs, validate_connector_config
from onyx.connectors.github.config import REPOSITORY_OWNER_ERROR
from onyx.connectors.google_drive.config import MY_DRIVE_EMAILS_EMPTY_ERROR
from onyx.connectors.jira.config import JQL_ORDER_BY_ERROR
from onyx.connectors.notion.config import ROOT_PAGE_ID_FORMAT_ERROR
from onyx.connectors.onedrive.config import USER_EMAIL_FORMAT_ERROR
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.sharepoint.config import SITE_URL_FORMAT_ERROR
from onyx.server.documents.capability_check_runs import plan_draft_capability_checks

_CONFLUENCE_FORM: dict[str, Any] = {
    "wiki_base": "https://example.atlassian.net",
    "is_cloud": True,
}
_JIRA_FORM: dict[str, Any] = {"jira_base_url": "https://example.atlassian.net"}
_GITHUB_FORM: dict[str, Any] = {"repo_owner": "onyx-dot-app"}
_NOTION_PAGE_ID = "17ab3186873d418fb899c3f6a43f68de"
_NOTION_DASHED_PAGE_ID = "17ab3186-873d-418f-b899-c3f6a43f68de"
_SHAREPOINT_SITE = "https://acme.sharepoint.com/sites/hr"


def _form_errors(source: DocumentSource, form_values: dict[str, Any]) -> dict[str, str]:
    return plan_draft_capability_checks(
        source=source,
        config_class=CONNECTOR_CLASS_MAP[source].config_class,
        access_type=None,
        form_values=form_values,
    ).form_errors


@pytest.mark.parametrize(
    "source,form_values,field,message",
    [
        (
            DocumentSource.CONFLUENCE,
            {**_CONFLUENCE_FORM, "page_id": "abc"},
            "page_id",
            PAGE_ID_FORMAT_ERROR,
        ),
        (
            DocumentSource.CONFLUENCE,
            {
                **_CONFLUENCE_FORM,
                "cql_query": "space = ENG AND lastModified > now('-7d')",
            },
            "cql_query",
            CQL_LAST_MODIFIED_ERROR,
        ),
        (
            DocumentSource.CONFLUENCE,
            {**_CONFLUENCE_FORM, "cql_query": "space = ENG order  by created"},
            "cql_query",
            CQL_ORDER_BY_ERROR,
        ),
        (
            DocumentSource.JIRA,
            {**_JIRA_FORM, "jql_query": "project = ENG ORDER BY created"},
            "jql_query",
            JQL_ORDER_BY_ERROR,
        ),
        (
            DocumentSource.GITHUB,
            {**_GITHUB_FORM, "repositories": "docs, onyx-dot-app/onyx"},
            "repositories",
            REPOSITORY_OWNER_ERROR,
        ),
        (
            DocumentSource.GOOGLE_DRIVE,
            {"my_drive_emails": " , "},
            "my_drive_emails",
            MY_DRIVE_EMAILS_EMPTY_ERROR,
        ),
        (
            DocumentSource.SHAREPOINT,
            {"sites": [_SHAREPOINT_SITE, "acme.sharepoint.com/hr"]},
            "sites",
            SITE_URL_FORMAT_ERROR,
        ),
        # Indexing validates every entry, blanks included.
        (
            DocumentSource.SHAREPOINT,
            {"sites": [""]},
            "sites",
            SITE_URL_FORMAT_ERROR,
        ),
        (
            DocumentSource.ONEDRIVE,
            {"users": ["jane@acme.com", "jane"]},
            "users",
            USER_EMAIL_FORMAT_ERROR,
        ),
        (
            DocumentSource.NOTION,
            {"root_page_id": "roadmap"},
            "root_page_id",
            ROOT_PAGE_ID_FORMAT_ERROR,
        ),
        (
            DocumentSource.NOTION,
            {"root_page_id": "https://example.com/Roadmap-" + _NOTION_PAGE_ID},
            "root_page_id",
            ROOT_PAGE_ID_FORMAT_ERROR,
        ),
    ],
)
def test_a_value_that_breaks_a_format_rule_is_a_form_error(
    source: DocumentSource,
    form_values: dict[str, Any],
    field: str,
    message: str,
) -> None:
    assert _form_errors(source, form_values) == {field: message}
    # Create and edit validate the full config with the same rule.
    with pytest.raises(ValueError, match=re.escape(message)):
        validate_connector_config(source, form_values)


@pytest.mark.parametrize(
    "source,form_values",
    [
        (DocumentSource.CONFLUENCE, {**_CONFLUENCE_FORM, "page_id": " 131368 "}),
        (DocumentSource.CONFLUENCE, {**_CONFLUENCE_FORM, "page_id": ""}),
        # The words are inside quoted values.
        (
            DocumentSource.CONFLUENCE,
            {**_CONFLUENCE_FORM, "cql_query": "title ~ 'lastModified notes'"},
        ),
        (
            DocumentSource.CONFLUENCE,
            {**_CONFLUENCE_FORM, "cql_query": 'text ~ "how order by works"'},
        ),
        (DocumentSource.JIRA, {**_JIRA_FORM, "jql_query": 'summary ~ "order by"'}),
        (DocumentSource.JIRA, {**_JIRA_FORM, "jql_query": None}),
        (DocumentSource.GITHUB, {**_GITHUB_FORM, "repositories": "onyx, docs"}),
        (DocumentSource.GITHUB, {**_GITHUB_FORM, "repositories": ""}),
        (
            DocumentSource.GOOGLE_DRIVE,
            {"my_drive_emails": "a@acme.com, ,b@acme.com"},
        ),
        (DocumentSource.GOOGLE_DRIVE, {"my_drive_emails": ""}),
        (DocumentSource.SHAREPOINT, {"sites": [_SHAREPOINT_SITE]}),
        (DocumentSource.SHAREPOINT, {"sites": []}),
        (DocumentSource.ONEDRIVE, {"users": [" Jane@acme.com ", " "]}),
        (DocumentSource.ONEDRIVE, {"users": None}),
        (DocumentSource.NOTION, {"root_page_id": f" {_NOTION_PAGE_ID} "}),
        (DocumentSource.NOTION, {"root_page_id": _NOTION_DASHED_PAGE_ID}),
        (
            DocumentSource.NOTION,
            {"root_page_id": f"https://www.notion.so/acme/Roadmap-{_NOTION_PAGE_ID}"},
        ),
        (DocumentSource.NOTION, {"root_page_id": ""}),
    ],
)
def test_a_value_that_follows_the_format_rules_is_no_form_error(
    source: DocumentSource, form_values: dict[str, Any]
) -> None:
    assert _form_errors(source, form_values) == {}


def test_a_stored_config_that_breaks_a_format_rule_still_builds_the_connector() -> None:
    stored = {**_GITHUB_FORM, "repositories": "onyx-dot-app/onyx"}

    assert build_connector_kwargs(DocumentSource.GITHUB, stored) == stored


def test_a_notion_page_url_reaches_the_connector_as_its_page_id() -> None:
    url = f"https://acme.notion.site/Roadmap-{_NOTION_PAGE_ID}?pvs=4"

    assert build_connector_kwargs(DocumentSource.NOTION, {"root_page_id": url}) == {
        "root_page_id": _NOTION_DASHED_PAGE_ID
    }
