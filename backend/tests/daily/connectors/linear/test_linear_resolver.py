"""Tests for LinearConnector.reindex against a real Linear workspace."""

import uuid
from collections.abc import Generator

import pytest

from onyx.connectors.linear.connector import LinearConnector
from onyx.connectors.linear.source_operations import API_KEY
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
)
from onyx.utils.variable_functionality import global_version
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.LINEAR_API_KEY)

# One crawl page is enough to find real issue ids, so the test stays fast.
_SAMPLE_SIZE = 5


def _make_connector(
    api_key: str, team_keys: list[str] | None = None
) -> LinearConnector:
    connector = LinearConnector(team_keys=team_keys, batch_size=_SAMPLE_SIZE)
    connector.load_credentials({API_KEY: api_key})
    return connector


@pytest.fixture
def api_key(test_secrets: dict[TestSecret, str]) -> str:
    return test_secrets[TestSecret.LINEAR_API_KEY].strip()


@pytest.fixture
def linear_connector(api_key: str) -> LinearConnector:
    return _make_connector(api_key)


@pytest.fixture
def crawled_docs(linear_connector: LinearConnector) -> list[Document]:
    """The first page of a normal crawl."""
    batch = next(linear_connector.load_from_state())
    docs = [d for d in batch if isinstance(d, Document)]
    assert docs, "The Linear test workspace must contain at least one issue"
    return docs


@pytest.fixture
def ee_enabled() -> Generator[None, None, None]:
    was_ee = global_version.is_ee_version()
    global_version.set_ee()
    yield
    if not was_ee:
        global_version.unset_ee()


def _build_failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id),
            failure_message="Synthetic failure for %s" % doc_id,
        )
        for doc_id in doc_ids
    ]


def _split(
    results: list[Document | ConnectorFailure | object],
) -> tuple[list[Document], list[ConnectorFailure]]:
    docs = [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]
    assert len(docs) + len(failures) == len(results)
    return docs, failures


def test_reindex_single_issue(
    linear_connector: LinearConnector, crawled_docs: list[Document]
) -> None:
    target = crawled_docs[0]

    docs, failures = _split(
        list(linear_connector.reindex(_build_failures([target.id])))
    )

    assert failures == []
    assert len(docs) == 1
    assert docs[0].id == target.id
    assert docs[0].semantic_identifier == target.semantic_identifier
    assert docs[0].sections == target.sections
    assert docs[0].external_access is None


def test_reindex_multiple_issues(
    linear_connector: LinearConnector, crawled_docs: list[Document]
) -> None:
    if len(crawled_docs) < 2:
        pytest.skip("The Linear test workspace has fewer than two issues")
    target_ids = [d.id for d in crawled_docs]

    docs, failures = _split(list(linear_connector.reindex(_build_failures(target_ids))))

    assert failures == []
    assert sorted(d.id for d in docs) == sorted(target_ids)


def test_reindex_mixed_batch_keeps_good_targets(
    linear_connector: LinearConnector, crawled_docs: list[Document]
) -> None:
    good = crawled_docs[0].id
    bogus = str(uuid.uuid4())
    weird = "ENG-123"

    docs, failures = _split(
        list(linear_connector.reindex(_build_failures([good, bogus, weird])))
    )

    assert [d.id for d in docs] == [good]
    assert sorted(
        f.failed_document.document_id for f in failures if f.failed_document
    ) == sorted([bogus, weird])


def test_reindex_unknown_issue_yields_failure(
    linear_connector: LinearConnector,
) -> None:
    bogus = str(uuid.uuid4())

    docs, failures = _split(list(linear_connector.reindex(_build_failures([bogus]))))

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == bogus


def test_reindex_unparseable_id_yields_failure(
    linear_connector: LinearConnector,
) -> None:
    weird = "https://linear.app/onyx/issue/ENG-1/not-an-id"

    docs, failures = _split(list(linear_connector.reindex(_build_failures([weird]))))

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == weird


def test_reindex_out_of_scope_issue_yields_failure(
    api_key: str, crawled_docs: list[Document]
) -> None:
    target = crawled_docs[0]
    assert target.doc_metadata is not None
    # An issue identifier is "<team key>-<number>".
    target_team_key = str(target.doc_metadata["hierarchy"]["identifier"]).rsplit(
        "-", 1
    )[0]
    other_team_keys = [
        team.key
        for team in _make_connector(api_key).ops.list_teams()
        if team.key != target_team_key
    ]
    if not other_team_keys:
        pytest.skip("The Linear test workspace has only one team")
    scoped = _make_connector(api_key, team_keys=[other_team_keys[0]])

    docs, failures = _split(list(scoped.reindex(_build_failures([target.id]))))

    assert docs == [], f"{target.id} of team {target_team_key} leaked out of scope"
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == target.id


def test_reindex_empty_errors(linear_connector: LinearConnector) -> None:
    assert list(linear_connector.reindex([])) == []


def test_reindex_entity_failures_are_skipped(
    linear_connector: LinearConnector,
) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="some_stage"),
        failure_message="retrieval failure",
    )

    assert list(linear_connector.reindex([entity])) == []


@pytest.mark.usefixtures("ee_enabled")
def test_reindex_with_permissions_sets_external_access(
    linear_connector: LinearConnector, crawled_docs: list[Document]
) -> None:
    target_ids = [d.id for d in crawled_docs]

    docs, failures = _split(
        list(
            linear_connector.reindex(
                _build_failures(target_ids), include_permissions=True
            )
        )
    )

    assert failures == []
    assert sorted(d.id for d in docs) == sorted(target_ids)
    teams = {team.id: team for team in linear_connector.ops.list_teams()}
    for doc in docs:
        access = doc.external_access
        assert access is not None, f"{doc.id} has no external access"
        assert access.is_public is False
        # Every issue is readable by its team's members.
        assert access.external_user_group_ids & set(teams), doc.id
