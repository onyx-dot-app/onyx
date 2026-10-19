"""JiraConnector.reindex against the real test project: a crawled issue comes
back under the same document id, a missing key and a foreign URL fail."""

import time

import pytest

from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.models import ConnectorFailure, Document, DocumentFailure
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.JIRA_USER_EMAIL, TestSecret.JIRA_API_TOKEN)

_JIRA_BASE_URL = "https://danswerai.atlassian.net"


@pytest.fixture
def jira_connector(test_secrets: dict[TestSecret, str]) -> JiraConnector:
    connector = JiraConnector(
        jira_base_url=_JIRA_BASE_URL, project_key="AS", comment_email_blacklist=[]
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return connector


def _failure(document_id: str) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(
            document_id=document_id, document_link=document_id
        ),
        failure_message="synthetic failure",
    )


def test_reindex_returns_crawled_issues_and_fails_the_rest(
    jira_connector: JiraConnector,
) -> None:
    crawled = load_all_from_connector(jira_connector, 0, time.time()).documents
    assert crawled, "The test project must hold at least one issue"
    target = crawled[0]
    missing = build_jira_url(_JIRA_BASE_URL, "AS-999999")
    foreign = "https://other.atlassian.net/browse/AS-1"

    outputs = list(
        jira_connector.reindex(
            [_failure(target.id), _failure(missing), _failure(foreign)]
        )
    )

    documents = [o for o in outputs if isinstance(o, Document)]
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert [d.id for d in documents] == [target.id]
    assert documents[0].semantic_identifier == target.semantic_identifier
    assert sorted(
        f.failed_document.document_id for f in failures if f.failed_document
    ) == sorted([missing, foreign])
