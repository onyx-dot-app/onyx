"""Tests for SlackConnector.reindex against the real Slack test workspace."""

import time

import pytest

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
)
from onyx.connectors.slack.connector import SlackConnector
from onyx.db.enums import HierarchyNodeType
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

PUBLIC_CHANNEL_NAME = "daily-connector-test-channel"
PRIVATE_CHANNEL_NAME = "private-channel"
PRIVATE_CHANNEL_USERS = {
    "admin@onyx-test.com",
    "test_user_1@onyx-test.com",
    # user 2 added via a group
    "test_user_2@onyx-test.com",
}

pytestmark = pytest.mark.secrets(TestSecret.SLACK_BOT_TOKEN)


def _make_connector(
    credentials_provider: OnyxStaticCredentialsProvider, channels: list[str]
) -> SlackConnector:
    connector = SlackConnector(channels=channels, use_redis=False)
    connector.set_credentials_provider(credentials_provider=credentials_provider)
    return connector


@pytest.fixture
def public_connector(
    slack_credentials_provider: OnyxStaticCredentialsProvider,
) -> SlackConnector:
    return _make_connector(slack_credentials_provider, [PUBLIC_CHANNEL_NAME])


@pytest.fixture
def two_channel_connector(
    slack_credentials_provider: OnyxStaticCredentialsProvider,
) -> SlackConnector:
    return _make_connector(
        slack_credentials_provider, [PUBLIC_CHANNEL_NAME, PRIVATE_CHANNEL_NAME]
    )


def _crawl_docs(connector: SlackConnector) -> list[Document]:
    return load_all_from_connector(connector, 0.0, time.time()).documents


def _build_failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id),
            failure_message="Synthetic failure for %s" % doc_id,
        )
        for doc_id in doc_ids
    ]


def _split(
    results: list[Document | ConnectorFailure | HierarchyNode],
) -> tuple[list[Document], list[ConnectorFailure], list[HierarchyNode]]:
    return (
        [r for r in results if isinstance(r, Document)],
        [r for r in results if isinstance(r, ConnectorFailure)],
        [r for r in results if isinstance(r, HierarchyNode)],
    )


def test_reindex_single_thread(public_connector: SlackConnector) -> None:
    crawled = _crawl_docs(public_connector)
    # Prefer a multi-message thread, so the test covers conversations.replies.
    target = max(crawled, key=lambda d: len(d.sections))

    docs, failures, nodes = _split(
        list(public_connector.reindex(_build_failures([target.id])))
    )

    assert failures == []
    assert len(docs) == 1
    assert docs[0].id == target.id
    assert [s.text for s in docs[0].sections] == [s.text for s in target.sections]
    assert docs[0].semantic_identifier == target.semantic_identifier
    assert docs[0].external_access is None
    assert len(nodes) == 1
    assert nodes[0].node_type == HierarchyNodeType.CHANNEL
    assert nodes[0].raw_node_id == docs[0].parent_hierarchy_raw_node_id


def test_reindex_multiple_threads_across_channels(
    two_channel_connector: SlackConnector,
) -> None:
    crawled = _crawl_docs(two_channel_connector)
    doc_ids = [d.id for d in crawled]
    channel_ids = {d.parent_hierarchy_raw_node_id for d in crawled}
    assert len(channel_ids) == 2, "Expected docs from both test channels"
    # Both doc shapes: a threaded message and a lone message.
    assert any(len(d.sections) > 1 for d in crawled)
    assert any(len(d.sections) == 1 for d in crawled)

    docs, failures, nodes = _split(
        list(two_channel_connector.reindex(_build_failures(doc_ids)))
    )

    assert failures == []
    assert {d.id for d in docs} == set(doc_ids)
    assert len(docs) == len(doc_ids)
    assert {n.raw_node_id for n in nodes} == channel_ids


def test_reindex_with_permissions(
    two_channel_connector: SlackConnector,
    enable_ee: None,  # noqa: ARG001
) -> None:
    crawled = _crawl_docs(two_channel_connector)

    docs, failures, nodes = _split(
        list(
            two_channel_connector.reindex(
                _build_failures([d.id for d in crawled]), include_permissions=True
            )
        )
    )

    assert failures == []
    assert len(docs) == len(crawled)
    private_docs = [d for d in docs if d.metadata["Channel"] == PRIVATE_CHANNEL_NAME]
    public_docs = [d for d in docs if d.metadata["Channel"] == PUBLIC_CHANNEL_NAME]
    assert private_docs and public_docs
    for doc in private_docs:
        assert doc.external_access is not None
        assert doc.external_access.is_public is False
        assert doc.external_access.external_user_emails == PRIVATE_CHANNEL_USERS
    for doc in public_docs:
        assert doc.external_access is not None
        assert doc.external_access.is_public is True
    for node in nodes:
        assert node.external_access is not None


def test_reindex_out_of_scope_channel_yields_failure(
    two_channel_connector: SlackConnector,
    public_connector: SlackConnector,
) -> None:
    private_ids = [
        d.id
        for d in _crawl_docs(two_channel_connector)
        if d.metadata["Channel"] == PRIVATE_CHANNEL_NAME
    ]
    assert private_ids

    docs, failures, _ = _split(
        list(public_connector.reindex(_build_failures(private_ids)))
    )

    assert docs == []
    assert [f.failed_document.document_id for f in failures if f.failed_document] == (
        private_ids
    )


def test_reindex_unknown_ids_yield_failures(public_connector: SlackConnector) -> None:
    channel_id = _crawl_docs(public_connector)[0].parent_hierarchy_raw_node_id
    assert channel_id
    unknown_thread = "%s__1000000000.000100" % channel_id
    unknown_channel = "C0000000000__1000000000.000100"

    docs, failures, _ = _split(
        list(
            public_connector.reindex(_build_failures([unknown_thread, unknown_channel]))
        )
    )

    assert docs == []
    assert {f.failed_document.document_id for f in failures if f.failed_document} == {
        unknown_thread,
        unknown_channel,
    }


def test_reindex_unparseable_id_yields_failure(
    public_connector: SlackConnector,
) -> None:
    weird = "https://example.slack.com/archives/C123/p1"

    docs, failures, nodes = _split(
        list(public_connector.reindex(_build_failures([weird])))
    )

    assert docs == []
    assert nodes == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == weird


def test_reindex_empty_errors(public_connector: SlackConnector) -> None:
    assert list(public_connector.reindex([])) == []


def test_reindex_entity_failures_are_skipped(
    public_connector: SlackConnector,
) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="C0000000000"),
        failure_message="channel failure",
    )

    assert list(public_connector.reindex([entity])) == []
