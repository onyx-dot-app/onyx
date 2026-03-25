"""Tests for OpenSearch search Prometheus metrics."""

from unittest.mock import patch

from onyx.document_index.opensearch.constants import OpenSearchSearchType
from onyx.server.metrics.opensearch_search import _client_duration
from onyx.server.metrics.opensearch_search import _search_total
from onyx.server.metrics.opensearch_search import _searches_in_progress
from onyx.server.metrics.opensearch_search import _server_duration
from onyx.server.metrics.opensearch_search import observe_opensearch_search
from onyx.server.metrics.opensearch_search import track_opensearch_search_in_progress


class TestObserveOpenSearchSearch:
    def test_increments_counter(self) -> None:
        search_type = OpenSearchSearchType.HYBRID
        before = _search_total.labels(search_type=search_type.value)._value.get()
        observe_opensearch_search(search_type, 0.1, 50)
        after = _search_total.labels(search_type=search_type.value)._value.get()
        assert after == before + 1

    def test_observes_client_duration(self) -> None:
        search_type = OpenSearchSearchType.KEYWORD
        before_sum = _client_duration.labels(search_type=search_type.value)._sum.get()
        observe_opensearch_search(search_type, 0.25, 100)
        after_sum = _client_duration.labels(search_type=search_type.value)._sum.get()
        assert after_sum == before_sum + 0.25

    def test_observes_server_duration(self) -> None:
        search_type = OpenSearchSearchType.SEMANTIC
        before_sum = _server_duration.labels(search_type=search_type.value)._sum.get()
        observe_opensearch_search(search_type, 0.3, 200)
        after_sum = _server_duration.labels(search_type=search_type.value)._sum.get()
        # 200ms should be recorded as 0.2s.
        assert after_sum == before_sum + 0.2

    def test_server_took_none_skips_server_histogram(self) -> None:
        search_type = OpenSearchSearchType.UNKNOWN
        before_server = _server_duration.labels(
            search_type=search_type.value
        )._sum.get()
        before_client = _client_duration.labels(
            search_type=search_type.value
        )._sum.get()
        before_total = _search_total.labels(search_type=search_type.value)._value.get()

        observe_opensearch_search(search_type, 0.1, None)

        # Server histogram should NOT be observed.
        after_server = _server_duration.labels(search_type=search_type.value)._sum.get()
        assert after_server == before_server

        # Client histogram and counter should still work.
        after_client = _client_duration.labels(search_type=search_type.value)._sum.get()
        after_total = _search_total.labels(search_type=search_type.value)._value.get()
        assert after_client == before_client + 0.1
        assert after_total == before_total + 1

    def test_exceptions_do_not_propagate(self) -> None:
        search_type = OpenSearchSearchType.RANDOM
        with patch.object(
            _search_total.labels(search_type=search_type.value),
            "inc",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise.
            observe_opensearch_search(search_type, 0.1, 50)


class TestTrackOpenSearchSearchInProgress:
    def test_gauge_increments_and_decrements(self) -> None:
        search_type = OpenSearchSearchType.HYBRID
        before = _searches_in_progress.labels(
            search_type=search_type.value
        )._value.get()

        with track_opensearch_search_in_progress(search_type):
            during = _searches_in_progress.labels(
                search_type=search_type.value
            )._value.get()
            assert during == before + 1

        after = _searches_in_progress.labels(search_type=search_type.value)._value.get()
        assert after == before

    def test_gauge_decrements_on_exception(self) -> None:
        search_type = OpenSearchSearchType.SEMANTIC
        before = _searches_in_progress.labels(
            search_type=search_type.value
        )._value.get()

        try:
            with track_opensearch_search_in_progress(search_type):
                raise ValueError("simulated search failure")
        except ValueError:
            pass

        after = _searches_in_progress.labels(search_type=search_type.value)._value.get()
        assert after == before

    def test_inc_exception_does_not_break_search(self) -> None:
        search_type = OpenSearchSearchType.KEYWORD
        before = _searches_in_progress.labels(
            search_type=search_type.value
        )._value.get()

        with patch.object(
            _searches_in_progress.labels(search_type=search_type.value),
            "inc",
            side_effect=RuntimeError("boom"),
        ):
            # Context manager should still yield without decrementing.
            with track_opensearch_search_in_progress(search_type):
                # Search logic would execute here.
                during = _searches_in_progress.labels(
                    search_type=search_type.value
                )._value.get()
                assert during == before

        after = _searches_in_progress.labels(search_type=search_type.value)._value.get()
        assert after == before
