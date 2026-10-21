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
from onyx.connectors.jira.config import JQL_ORDER_BY_ERROR
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.server.documents.capability_check_runs import plan_draft_capability_checks

_CONFLUENCE_FORM: dict[str, Any] = {
    "wiki_base": "https://example.atlassian.net",
    "is_cloud": True,
}
_JIRA_FORM: dict[str, Any] = {"jira_base_url": "https://example.atlassian.net"}
_GITHUB_FORM: dict[str, Any] = {"repo_owner": "onyx-dot-app"}


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
    ],
)
def test_a_value_that_follows_the_format_rules_is_no_form_error(
    source: DocumentSource, form_values: dict[str, Any]
) -> None:
    assert _form_errors(source, form_values) == {}


def test_a_stored_config_that_breaks_a_format_rule_still_builds_the_connector() -> None:
    stored = {**_GITHUB_FORM, "repositories": "onyx-dot-app/onyx"}

    assert build_connector_kwargs(DocumentSource.GITHUB, stored) == stored
