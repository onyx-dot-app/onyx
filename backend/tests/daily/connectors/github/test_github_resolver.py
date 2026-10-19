"""GithubConnector.reindex against the real docs repository: a crawled pull
request comes back under the same document id, a missing one fails."""

import time

import pytest

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.models import ConnectorFailure, Document, DocumentFailure
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.ACCESS_TOKEN_GITHUB)


@pytest.fixture
def github_connector(test_secrets: dict[TestSecret, str]) -> GithubConnector:
    connector = GithubConnector(
        repo_owner="onyx-dot-app",
        repositories="documentation",
        include_prs=True,
        include_issues=True,
    )
    connector.load_credentials(
        {"github_access_token": test_secrets[TestSecret.ACCESS_TOKEN_GITHUB]}
    )
    return connector


def _failure(document_id: str) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(
            document_id=document_id, document_link=document_id
        ),
        failure_message="synthetic failure",
    )


def test_reindex_returns_crawled_pull_requests_and_fails_the_rest(
    github_connector: GithubConnector,
) -> None:
    crawled = load_all_from_connector(github_connector, 0, time.time()).documents
    pull_requests = [d for d in crawled if "/pull/" in d.id]
    assert pull_requests, "The docs repository must hold at least one pull request"
    target = pull_requests[0]
    missing = "https://github.com/onyx-dot-app/documentation/pull/999999"
    foreign = "https://example.com/not/a/document"

    outputs = list(
        github_connector.reindex(
            [_failure(target.id), _failure(missing), _failure(foreign)]
        )
    )

    documents = [o for o in outputs if isinstance(o, Document)]
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert [d.id for d in documents] == [target.id]
    assert documents[0].semantic_identifier == target.semantic_identifier
    assert [f.failed_document.document_id for f in failures if f.failed_document] == [
        missing,
        foreign,
    ]
