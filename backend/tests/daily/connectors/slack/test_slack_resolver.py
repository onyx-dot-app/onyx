"""SlackConnector.reindex against the real daily test channel: a crawled
thread comes back under the same document id, and a missing one fails."""

import time

import pytest

from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
)
from onyx.connectors.slack.connector import SlackConnector
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.SLACK_BOT_TOKEN)


def _failure(document_id: str) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=document_id, document_link=None),
        failure_message="synthetic failure",
    )


@pytest.mark.parametrize(
    "slack_connector", ["daily-connector-test-channel"], indirect=True
)
def test_reindex_returns_crawled_threads_and_fails_missing_ones(
    slack_connector: SlackConnector,
) -> None:
    crawled = load_all_from_connector(slack_connector, 0, time.time()).documents
    assert crawled, "The test channel must hold at least one message"
    target = crawled[0]
    channel_id = target.id.split("__", 1)[0]
    missing = f"{channel_id}__1.000001"

    outputs = list(slack_connector.reindex([_failure(target.id), _failure(missing)]))

    documents = [o for o in outputs if isinstance(o, Document)]
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    nodes = [o for o in outputs if isinstance(o, HierarchyNode)]
    assert [d.id for d in documents] == [target.id]
    assert documents[0].semantic_identifier == target.semantic_identifier
    assert len(documents[0].sections) == len(target.sections)
    assert [n.raw_node_id for n in nodes] == [channel_id]
    assert [f.failed_document.document_id for f in failures if f.failed_document] == [
        missing
    ]
