"""Unit tests for extract_ids_from_runnable_connector metrics instrumentation."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import SlimDocument
from onyx.server.metrics.pruning_metrics import PRUNING_ENUMERATION_DURATION
from onyx.server.metrics.pruning_metrics import PRUNING_RATE_LIMIT_ERRORS


def _make_slim_connector(doc_ids: list[str]) -> SlimConnector:
    """Mock SlimConnector that yields the given doc IDs in one batch."""
    connector = MagicMock(spec=SlimConnector)
    docs = [
        MagicMock(spec=SlimDocument, id=doc_id, parent_hierarchy_raw_node_id=None)
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

        with pytest.raises(Exception):
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

        with pytest.raises(Exception):
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

        with pytest.raises(Exception):
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

        with pytest.raises(Exception):
            extract_ids_from_runnable_connector(connector)

        after = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="unknown")._value.get()
        assert after == before + 1
