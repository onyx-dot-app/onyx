"""Live Jira Service Management indexing.

Set these environment variables, then run this file:

- ``JSM_BASE_URL``: the site, for example ``https://example.atlassian.net``
- ``JSM_USER_EMAIL``: the agent account email. Leave unset on Data Center.
- ``JSM_API_TOKEN``: a Cloud API token, or a Data Center personal access token
- ``JSM_PROJECT_KEY``: the service project key

The project must contain two requests. The defaults below describe them, and
each one can be overridden to match an existing site:

- ``JSM_TEST_SUMMARY`` (default ``VPN is down``) with the description text
  ``JSM_TEST_DESCRIPTION`` (default ``Cannot connect since Monday``), a public
  comment containing ``JSM_TEST_PUBLIC_COMMENT`` (default ``We are looking``),
  and an internal comment containing ``JSM_TEST_INTERNAL_COMMENT`` (default
  ``Agent only note``).
- ``JSM_TEST_SECOND_SUMMARY`` (default ``New laptop``) with the description text
  ``JSM_TEST_SECOND_DESCRIPTION`` (default ``Need a replacement``).

Text checks match substrings, so a longer description or comment still passes.
The account must be an agent on that service desk. Without the connection
variables the test is skipped.
"""

import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document, SlimDocument, TextSection
from tests.daily.connectors.utils import load_all_from_connector

_REQUIRED = ("JSM_BASE_URL", "JSM_API_TOKEN", "JSM_PROJECT_KEY")

pytestmark = pytest.mark.skipif(
    any(not os.environ.get(name) for name in _REQUIRED),
    reason="Set JSM_BASE_URL, JSM_API_TOKEN, and JSM_PROJECT_KEY to run the live test.",
)


def _seed(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


SUMMARY = _seed("JSM_TEST_SUMMARY", "VPN is down")
DESCRIPTION = _seed("JSM_TEST_DESCRIPTION", "Cannot connect since Monday")
PUBLIC_COMMENT = _seed("JSM_TEST_PUBLIC_COMMENT", "We are looking")
INTERNAL_COMMENT = _seed("JSM_TEST_INTERNAL_COMMENT", "Agent only note")
SECOND_SUMMARY = _seed("JSM_TEST_SECOND_SUMMARY", "New laptop")
SECOND_DESCRIPTION = _seed("JSM_TEST_SECOND_DESCRIPTION", "Need a replacement")


def _connector(include_internal_comments: bool) -> JiraServiceManagementConnector:
    email = os.environ.get("JSM_USER_EMAIL", "").strip()
    credentials: dict[str, str] = {"jira_api_token": os.environ["JSM_API_TOKEN"]}
    if email:
        credentials["jira_user_email"] = email
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_BASE_URL"],
        project_key=os.environ["JSM_PROJECT_KEY"],
        include_internal_comments=include_internal_comments,
    )
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            None,
            DocumentSource.JIRA_SERVICE_MANAGEMENT.value,
            credentials,
        )
    )
    return connector


def _texts(document: Document) -> list[str]:
    return [
        section.text
        for section in document.sections
        if isinstance(section, TextSection)
    ]


def _contains(texts: list[str], expected: str) -> bool:
    return any(expected in text for text in texts)


def _load(connector: JiraServiceManagementConnector) -> dict[str, Document]:
    output = load_all_from_connector(
        connector=connector,
        start=0,
        end=time.time(),
    )
    assert not output.failures
    return {
        document.title: document
        for document in output.documents
        if document.title is not None
    }


def test_seeded_requests_and_comments_are_indexed() -> None:
    connector = _connector(include_internal_comments=True)
    connector.validate_connector_settings()
    by_title = _load(connector)

    first = by_title.get(SUMMARY)
    second = by_title.get(SECOND_SUMMARY)
    assert isinstance(first, Document), sorted(by_title)
    assert isinstance(second, Document), sorted(by_title)
    assert first.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert first.semantic_identifier.startswith("[")
    assert first.metadata.get("project") == connector.project_key

    first_text = _texts(first)
    assert _contains(first_text, DESCRIPTION)
    assert _contains(first_text, PUBLIC_COMMENT)
    assert _contains(first_text, INTERNAL_COMMENT)
    assert _contains(_texts(second), SECOND_DESCRIPTION)

    slim = {
        document.id
        for batch in connector.retrieve_all_slim_docs()
        for document in batch
        if isinstance(document, SlimDocument)
    }
    indexed = {document.id for document in by_title.values()}
    assert {first.id, second.id} <= slim
    assert indexed <= slim


def test_internal_comments_are_left_out_when_disabled() -> None:
    by_title = _load(_connector(include_internal_comments=False))

    first = by_title.get(SUMMARY)
    assert isinstance(first, Document), sorted(by_title)
    first_text = _texts(first)
    assert _contains(first_text, PUBLIC_COMMENT)
    assert not _contains(first_text, INTERNAL_COMMENT)
