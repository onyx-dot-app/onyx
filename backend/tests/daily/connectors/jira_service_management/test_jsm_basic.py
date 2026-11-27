"""Live Jira Service Management indexing.

Set these environment variables, then run this file:

- ``JSM_BASE_URL``: the site, for example ``https://example.atlassian.net``
- ``JSM_USER_EMAIL``: the agent account email. Leave unset on Data Center.
- ``JSM_API_TOKEN``: a Cloud API token, or a Data Center personal access token
- ``JSM_PROJECT_KEY``: the service project key

The project must contain two requests:

- Summary ``VPN is down``, description ``Cannot connect since Monday``,
  a public comment ``We are looking``, and an internal comment ``Agent only note``.
- Summary ``New laptop``, description ``Need a replacement``.

The account must be an agent on that service desk. Without the variables the
test is skipped.
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


def _connector() -> JiraServiceManagementConnector:
    email = os.environ.get("JSM_USER_EMAIL", "").strip()
    credentials: dict[str, str] = {"jira_api_token": os.environ["JSM_API_TOKEN"]}
    if email:
        credentials["jira_user_email"] = email
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_BASE_URL"],
        project_key=os.environ["JSM_PROJECT_KEY"],
        include_internal_comments=True,
    )
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            None,
            DocumentSource.JIRA_SERVICE_MANAGEMENT.value,
            credentials,
        )
    )
    return connector


def test_seeded_requests_and_comments_are_indexed() -> None:
    connector = _connector()
    output = load_all_from_connector(
        connector=connector,
        start=0,
        end=time.time(),
    )
    by_title = {document.title: document for document in output.documents}

    vpn = by_title.get("VPN is down")
    laptop = by_title.get("New laptop")
    assert isinstance(vpn, Document)
    assert isinstance(laptop, Document)

    vpn_text = [
        section.text for section in vpn.sections if isinstance(section, TextSection)
    ]
    assert "Cannot connect since Monday" in vpn_text
    assert "We are looking" in vpn_text
    assert "Agent only note" in vpn_text
    laptop_text = [
        section.text for section in laptop.sections if isinstance(section, TextSection)
    ]
    assert "Need a replacement" in laptop_text

    indexed = {document.id for document in output.documents}
    slim = {
        document.id
        for batch in connector.retrieve_all_slim_docs()
        for document in batch
        if isinstance(document, SlimDocument)
    }
    assert {vpn.id, laptop.id} <= slim
    assert {vpn.id, laptop.id} <= indexed
