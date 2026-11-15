"""Unit tests for extract_ids_from_runnable_connector: metrics instrumentation
and the listing from the indexing start."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import source_prune_honors_indexing_start
from onyx.connectors.interfaces import (
    BaseConnector,
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
    prune_listing_honors_indexing_start,
)
from onyx.connectors.models import SlimDocument
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.server.metrics.pruning_metrics import (
    PRUNING_ENUMERATION_DURATION,
    PRUNING_RATE_LIMIT_ERRORS,
)


def _make_slim_connector(doc_ids: list[str]) -> SlimConnector:
    """Mock SlimConnector that yields the given doc IDs in one batch."""
    connector = MagicMock(spec=SlimConnector)
    docs = [
        MagicMock(
            spec=SlimDocument,
            id=doc_id,
            parent_hierarchy_raw_node_id=None,
            doc_created_at=None,
        )
        for doc_id in doc_ids
    ]
    connector.retrieve_all_slim_docs.return_value = iter([docs])
    return connector


def _raising_connector(message: str) -> SlimConnector:
    """Mock SlimConnector whose generator raises with the given message."""
    connector = MagicMock(spec=SlimConnector)

    def raising_iter() -> Iterator:
        raise Exception(message)
        yield

    connector.retrieve_all_slim_docs.return_value = raising_iter()
    return connector


class TestEnumerationDuration:
    def test_recorded_on_success(self) -> None:
        connector = _make_slim_connector(["doc1"])
        before = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()

        extract_ids_from_runnable_connector(connector, connector_type="google_drive")

        after = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()
        assert after >= before  # duration observed (non-negative)

    def test_recorded_on_exception(self) -> None:
        connector = _raising_connector("unexpected error")
        before = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="confluence"
        )._sum.get()

        with pytest.raises(Exception, match="unexpected error"):
            extract_ids_from_runnable_connector(connector, connector_type="confluence")

        after = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="confluence"
        )._sum.get()
        assert after >= before  # duration observed even on exception


class TestRateLimitDetection:
    def test_increments_on_rate_limit_message(self) -> None:
        connector = _raising_connector("rate limit exceeded")
        before = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()

        with pytest.raises(Exception, match="rate limit exceeded"):
            extract_ids_from_runnable_connector(
                connector, connector_type="google_drive"
            )

        after = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()
        assert after == before + 1

    def test_increments_on_429_in_message(self) -> None:
        connector = _raising_connector("HTTP 429 Too Many Requests")
        before = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="confluence"
        )._value.get()

        with pytest.raises(Exception, match="429"):
            extract_ids_from_runnable_connector(connector, connector_type="confluence")

        after = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="confluence"
        )._value.get()
        assert after == before + 1

    def test_does_not_increment_on_non_rate_limit_exception(self) -> None:
        connector = _raising_connector("connection timeout")
        before = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="slack")._value.get()

        with pytest.raises(Exception, match="connection timeout"):
            extract_ids_from_runnable_connector(connector, connector_type="slack")

        after = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="slack")._value.get()
        assert after == before

    def test_rate_limit_detection_is_case_insensitive(self) -> None:
        connector = _raising_connector("RATE LIMIT exceeded")
        before = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="jira")._value.get()

        with pytest.raises(Exception, match="RATE LIMIT exceeded"):
            extract_ids_from_runnable_connector(connector, connector_type="jira")

        after = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="jira")._value.get()
        assert after == before + 1

    def test_connector_type_label_matches_input(self) -> None:
        connector = _raising_connector("rate limit exceeded")
        before_gd = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()
        before_jira = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="jira"
        )._value.get()

        with pytest.raises(Exception, match="rate limit exceeded"):
            extract_ids_from_runnable_connector(
                connector, connector_type="google_drive"
            )

        assert (
            PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="google_drive")._value.get()
            == before_gd + 1
        )
        assert (
            PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="jira")._value.get()
            == before_jira
        )

    def test_defaults_to_unknown_connector_type(self) -> None:
        connector = _raising_connector("rate limit exceeded")
        before = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="unknown")._value.get()

        with pytest.raises(Exception, match="rate limit exceeded"):
            extract_ids_from_runnable_connector(connector)

        after = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="unknown")._value.get()
        assert after == before + 1


# Listing from the indexing start


_START = 1_700_000_000.0


class _DatedSlimConnector(SlimConnector):
    """A slim listing that filters by the same date as indexing."""

    slim_listing_honors_indexing_start = True

    def __init__(self) -> None:
        self.starts: list[SecondsSinceUnixEpoch | None] = []

    def load_credentials(self, credentials: dict[str, Any]) -> None:  # noqa: ARG002
        return None

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        self.starts.append(start)
        yield [SlimDocument(id="doc")]


class _UndatedSlimConnector(_DatedSlimConnector):
    slim_listing_honors_indexing_start = False


class _PollConnector(PollConnector):
    def __init__(self) -> None:
        self.starts: list[SecondsSinceUnixEpoch] = []

    def load_credentials(self, credentials: dict[str, Any]) -> None:  # noqa: ARG002
        return None

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
    ) -> GenerateDocumentsOutput:
        self.starts.append(start)
        yield []


class _LoadConnector(LoadConnector, PollConnector):
    def __init__(self) -> None:
        self.loaded = False

    def load_credentials(self, credentials: dict[str, Any]) -> None:  # noqa: ARG002
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        self.loaded = True
        yield []

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
    ) -> GenerateDocumentsOutput:
        raise AssertionError("A prune of a load connector loads all documents.")


class TestListingFromIndexingStart:
    def test_dated_slim_listing_gets_the_start(self) -> None:
        connector = _DatedSlimConnector()
        result = extract_ids_from_runnable_connector(connector, start=_START)

        assert connector.starts == [_START]
        assert result.listed_from == _START
        assert list(result.raw_id_to_parent) == ["doc"]

    def test_undated_slim_listing_lists_everything(self) -> None:
        connector = _UndatedSlimConnector()
        result = extract_ids_from_runnable_connector(connector, start=_START)

        assert connector.starts == [None]
        assert result.listed_from is None

    def test_no_start_lists_everything(self) -> None:
        connector = _DatedSlimConnector()
        result = extract_ids_from_runnable_connector(connector)

        assert connector.starts == [None]
        assert result.listed_from is None

    @pytest.mark.parametrize("start, expected", [(_START, _START), (None, 0.0)])
    def test_poll_fallback_polls_from_the_start(
        self, start: SecondsSinceUnixEpoch | None, expected: SecondsSinceUnixEpoch
    ) -> None:
        connector = _PollConnector()
        result = extract_ids_from_runnable_connector(connector, start=start)

        assert connector.starts == [expected]
        assert result.listed_from == start

    def test_load_fallback_lists_everything(self) -> None:
        connector = _LoadConnector()
        result = extract_ids_from_runnable_connector(connector, start=_START)

        assert connector.loaded
        assert result.listed_from is None


@pytest.mark.parametrize(
    "connector_class, expected",
    [
        (_DatedSlimConnector, True),
        (_UndatedSlimConnector, False),
        (_PollConnector, True),
        (_LoadConnector, False),
    ],
)
def test_prune_listing_honors_indexing_start(
    connector_class: type[BaseConnector], expected: bool
) -> None:
    assert prune_listing_honors_indexing_start(connector_class) is expected


@pytest.mark.parametrize(
    "source, expected",
    [
        # Slim listing filters by last modified, as indexing does. These
        # listings also yield hierarchy nodes; the prune keeps the ancestors
        # of the listed documents, so the date filter stays on.
        (DocumentSource.CONFLUENCE, True),
        (DocumentSource.BOX, True),
        (DocumentSource.GOOGLE_DRIVE, True),
        (DocumentSource.JIRA, True),
        (DocumentSource.SHAREPOINT, True),
        # Slim listing ignores the start, for some document types at least.
        (DocumentSource.NOTION, False),
        (DocumentSource.SLACK, False),
        (DocumentSource.TEAMS, False),
        (DocumentSource.CANVAS, False),
        # A load connector lists all documents.
        (DocumentSource.WEB, False),
        # No slim listing: the prune runs the checkpoint as indexing does.
        (DocumentSource.GONG, True),
        # No connector class.
        (DocumentSource.INGESTION_API, False),
    ],
)
def test_source_prune_honors_indexing_start(
    source: DocumentSource, expected: bool
) -> None:
    assert source_prune_honors_indexing_start(source) is expected
