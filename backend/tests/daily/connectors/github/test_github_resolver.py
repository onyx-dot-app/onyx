"""Tests for GithubConnector.reindex against a real GitHub repository."""

from collections.abc import Generator

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
)
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.ACCESS_TOKEN_GITHUB)

_OWNER = "onyx-dot-app"
_REPO = "documentation"
_REPO_URL = f"https://github.com/{_OWNER}/{_REPO}"


def _make_connector(access_token: str) -> GithubConnector:
    connector = GithubConnector(
        repo_owner=_OWNER,
        repositories=_REPO,
        include_prs=True,
        include_issues=True,
        include_files=True,
    )
    connector.load_credentials({"github_access_token": access_token})
    return connector


@pytest.fixture
def github_connector(test_secrets: dict[TestSecret, str]) -> GithubConnector:
    return _make_connector(test_secrets[TestSecret.ACCESS_TOKEN_GITHUB])


@pytest.fixture(scope="module")
def doc_ids_by_kind(
    test_secrets: dict[TestSecret, str],
) -> dict[str, list[str]]:
    """Real doc ids from the slim crawl, which writes the same ids as the
    full crawl but reads no content."""
    connector = _make_connector(test_secrets[TestSecret.ACCESS_TOKEN_GITHUB])
    by_kind: dict[str, list[str]] = {"pull": [], "issues": [], "blob": []}
    for batch in connector.retrieve_all_slim_docs():
        for doc in batch:
            if not isinstance(doc, SlimDocument):
                continue
            for kind, ids in by_kind.items():
                if f"{_REPO_URL}/{kind}/" in doc.id:
                    ids.append(doc.id)
    for kind, ids in by_kind.items():
        assert ids, f"Test repository has no '{kind}' documents"
    return by_kind


@pytest.fixture
def ee_enabled(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    fetch_versioned_implementation.cache_clear()
    monkeypatch.setattr(global_version, "is_ee_version", lambda: True)
    yield
    fetch_versioned_implementation.cache_clear()


def _build_failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id, document_link=doc_id),
            failure_message=f"Synthetic failure for {doc_id}",
        )
        for doc_id in doc_ids
    ]


def _split(
    results: list[Document | ConnectorFailure | HierarchyNode],
) -> tuple[list[Document], list[ConnectorFailure]]:
    assert not [r for r in results if isinstance(r, HierarchyNode)]
    return (
        [r for r in results if isinstance(r, Document)],
        [r for r in results if isinstance(r, ConnectorFailure)],
    )


def test_reindex_single_pull_request(
    github_connector: GithubConnector,
    doc_ids_by_kind: dict[str, list[str]],
) -> None:
    target = doc_ids_by_kind["pull"][0]

    docs, failures = _split(list(github_connector.reindex(_build_failures([target]))))

    assert failures == []
    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == target
    assert doc.source == DocumentSource.GITHUB
    assert doc.metadata.get("object_type") == "PullRequest"
    assert doc.external_access is None


def test_reindex_every_doc_type(
    github_connector: GithubConnector,
    doc_ids_by_kind: dict[str, list[str]],
) -> None:
    targets = (
        doc_ids_by_kind["pull"][:2]
        + doc_ids_by_kind["issues"][:2]
        + doc_ids_by_kind["blob"][:2]
    )

    docs, failures = _split(list(github_connector.reindex(_build_failures(targets))))

    assert failures == []
    assert sorted(d.id for d in docs) == sorted(targets)
    object_types = {d.metadata.get("object_type") for d in docs}
    assert object_types == {"PullRequest", "Issue", "File"}
    for doc in docs:
        assert doc.sections and doc.sections[0].link == doc.id


def test_reindex_with_permissions(
    ee_enabled: None,  # noqa: ARG001
    github_connector: GithubConnector,
    doc_ids_by_kind: dict[str, list[str]],
) -> None:
    targets = [
        doc_ids_by_kind["pull"][0],
        doc_ids_by_kind["issues"][0],
        doc_ids_by_kind["blob"][0],
    ]

    docs, failures = _split(
        list(
            github_connector.reindex(_build_failures(targets), include_permissions=True)
        )
    )

    assert failures == []
    assert sorted(d.id for d in docs) == sorted(targets)
    for doc in docs:
        # The test repository is public.
        assert doc.external_access is not None
        assert doc.external_access.is_public


def test_reindex_unknown_targets_yield_failures(
    github_connector: GithubConnector,
) -> None:
    bogus = [
        f"{_REPO_URL}/pull/99999999",
        f"{_REPO_URL}/issues/99999999",
        f"{_REPO_URL}/blob/main/does-not-exist-onyx-test.md",
        # Out of the configured scope.
        "https://github.com/some-other-owner/documentation/pull/1",
        f"https://github.com/{_OWNER}/not-a-configured-repo/pull/1",
    ]

    docs, failures = _split(list(github_connector.reindex(_build_failures(bogus))))

    assert docs == []
    assert sorted(
        f.failed_document.document_id for f in failures if f.failed_document
    ) == sorted(bogus)


def test_reindex_unparseable_ids_yield_failures(
    github_connector: GithubConnector,
) -> None:
    weird = [
        "not a url",
        f"{_REPO_URL}/pull/not-a-number",
        f"{_REPO_URL}/discussions/1",
        f"{_REPO_URL}/blob/main",
    ]

    docs, failures = _split(list(github_connector.reindex(_build_failures(weird))))

    assert docs == []
    assert sorted(
        f.failed_document.document_id for f in failures if f.failed_document
    ) == sorted(weird)


def test_reindex_empty_errors(github_connector: GithubConnector) -> None:
    assert list(github_connector.reindex([])) == []


def test_reindex_entity_failures_are_skipped(
    github_connector: GithubConnector,
) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id=f"{_OWNER}/{_REPO}:files"),
        failure_message="retrieval failure",
    )

    assert list(github_connector.reindex([entity])) == []
