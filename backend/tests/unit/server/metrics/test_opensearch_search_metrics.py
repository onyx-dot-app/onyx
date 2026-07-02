"""Tests for OpenSearch search Prometheus metrics."""

from unittest.mock import patch

import pytest

from onyx.document_index.opensearch.constants import OpenSearchSearchType
from onyx.server.metrics.opensearch_search import _client_duration
from onyx.server.metrics.opensearch_search import _client_server_overhead
from onyx.server.metrics.opensearch_search import _search_errors
from onyx.server.metrics.opensearch_search import _search_total
from onyx.server.metrics.opensearch_search import _searches_in_progress
from onyx.server.metrics.opensearch_search import _server_duration
from onyx.server.metrics.opensearch_search import observe_opensearch_search
from onyx.server.metrics.opensearch_search import record_opensearch_search_error
from onyx.server.metrics.opensearch_search import track_opensearch_search


class TestRecordOpenSearchSearchError:
    def test_increments_error_counter_with_exception_class_name(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.HYBRID
        error_type = "ValueError"
        before = _search_errors.labels(
            search_type=search_type.value, error_type=error_type
        )._value.get()

        # Under test.
        record_opensearch_search_error(search_type, ValueError("boom"))

        # Postcondition.
        after = _search_errors.labels(
            search_type=search_type.value, error_type=error_type
        )._value.get()
        assert after == before + 1

    def test_distinguishes_error_types(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.KEYWORD
        before_value = _search_errors.labels(
            search_type=search_type.value, error_type="ValueError"
        )._value.get()
        before_runtime = _search_errors.labels(
            search_type=search_type.value, error_type="RuntimeError"
        )._value.get()

        # Under test.
        record_opensearch_search_error(search_type, ValueError("a"))
        record_opensearch_search_error(search_type, RuntimeError("b"))

        # Postcondition.
        after_value = _search_errors.labels(
            search_type=search_type.value, error_type="ValueError"
        )._value.get()
        after_runtime = _search_errors.labels(
            search_type=search_type.value, error_type="RuntimeError"
        )._value.get()
        assert after_value == before_value + 1
        assert after_runtime == before_runtime + 1

    def test_exceptions_do_not_propagate(self) -> None:
        # Precondition.
        # _search_errors has two labels (search_type, error_type), so we can't
        # call .labels() with a single label in the test setup — that itself
        # raises ValueError before patching takes effect. Instead, patch .labels
        # on the counter and have the returned child's .inc() raise when the
        # production code reaches it.
        search_type = OpenSearchSearchType.RANDOM
        with patch.object(_search_errors, "labels") as labels_mock:
            labels_mock.return_value.inc.side_effect = RuntimeError("boom")

            # Under test and postcondition.
            # Should not raise.
            record_opensearch_search_error(
                search_type, ValueError("simulated search failure")
            )

            # Sanity check: the production code reached the fully-labeled child
            # for this specific error_type.
            labels_mock.assert_called_once_with(
                search_type=search_type.value, error_type="ValueError"
            )


class TestObserveOpenSearchSearch:
    def test_does_not_increment_attempt_counter(self) -> None:
        # Precondition.
        # observe_opensearch_search must not touch _search_total; the attempt
        # counter is the responsibility of record_opensearch_search_attempt so
        # that failures count toward the denominator.
        search_type = OpenSearchSearchType.HYBRID
        before = _search_total.labels(search_type=search_type.value)._value.get()

        # Under test.
        observe_opensearch_search(search_type, 0.1, 50)

        # Postcondition.
        after = _search_total.labels(search_type=search_type.value)._value.get()
        assert after == before

    def test_observes_client_duration(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.KEYWORD
        before_sum = _client_duration.labels(search_type=search_type.value)._sum.get()

        # Under test.
        observe_opensearch_search(search_type, 0.25, 100)

        # Postcondition.
        after_sum = _client_duration.labels(search_type=search_type.value)._sum.get()
        assert after_sum == before_sum + 0.25

    def test_observes_server_duration(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.SEMANTIC
        before_sum = _server_duration.labels(search_type=search_type.value)._sum.get()

        # Under test.
        observe_opensearch_search(search_type, 0.3, 200)

        # Postcondition.
        after_sum = _server_duration.labels(search_type=search_type.value)._sum.get()
        # 200ms should be recorded as 0.2s.
        assert after_sum == before_sum + 0.2

    def test_server_took_none_skips_server_histogram(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.UNKNOWN
        before_server = _server_duration.labels(
            search_type=search_type.value
        )._sum.get()
        before_client = _client_duration.labels(
            search_type=search_type.value
        )._sum.get()
        before_overhead = _client_server_overhead.labels(
            search_type=search_type.value
        )._sum.get()

        # Under test.
        observe_opensearch_search(search_type, 0.1, None)

        # Postcondition.
        # Server histogram should NOT be observed.
        after_server = _server_duration.labels(search_type=search_type.value)._sum.get()
        assert after_server == before_server

        # Overhead must NOT be observed when server_took_ms is None — we don't
        # have a comparable server-side baseline.
        after_overhead = _client_server_overhead.labels(
            search_type=search_type.value
        )._sum.get()
        assert after_overhead == before_overhead

        # Client histogram should still work.
        after_client = _client_duration.labels(search_type=search_type.value)._sum.get()
        assert after_client == before_client + 0.1

    def test_observes_overhead_when_both_durations_known(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.HYBRID
        child = _client_server_overhead.labels(search_type=search_type.value)
        before_sum = child._sum.get()
        # prometheus_client stores per-bucket counts non-cumulatively, so the
        # total observation count is the sum across all buckets.
        before_count = sum(b.get() for b in child._buckets)

        # Under test.
        # Client 0.5s, server 200ms (0.2s) -> overhead 0.3s.
        observe_opensearch_search(search_type, 0.5, 200)

        # Postcondition.
        after_sum = child._sum.get()
        after_count = sum(b.get() for b in child._buckets)
        assert after_sum == pytest.approx(before_sum + 0.3)
        assert after_count == before_count + 1

    def test_overhead_drops_negative_observation(self) -> None:
        # If server 'took' exceeds the client wall-clock duration (likely a
        # timekeeping bug on the OpenSearch side), the raw diff is negative. The
        # observation is dropped entirely with a warning — neither sum nor count
        # change on the overhead histogram. A negative observation against
        # non-negative buckets would land in every bucket and corrupt quantile
        # estimation, so dropping is preferable to recording. The client and
        # server histograms still get their samples because they were observed
        # before the negative check.
        # Precondition.
        search_type = OpenSearchSearchType.KEYWORD
        overhead_child = _client_server_overhead.labels(search_type=search_type.value)
        client_child = _client_duration.labels(search_type=search_type.value)
        server_child = _server_duration.labels(search_type=search_type.value)
        before_overhead_sum = overhead_child._sum.get()
        # prometheus_client stores per-bucket counts non-cumulatively, so the
        # total observation count is the sum across all buckets.
        before_overhead_count = sum(b.get() for b in overhead_child._buckets)
        before_client_sum = client_child._sum.get()
        before_server_sum = server_child._sum.get()

        # Under test.
        # Client 0.1s, server 500ms (0.5s) -> raw diff = -0.4s.
        observe_opensearch_search(search_type, 0.1, 500)

        # Postcondition.
        # Overhead histogram untouched, but client and server latency are still
        # observed (the negative-overhead bailout happens after those
        # observations land).
        after_overhead_sum = overhead_child._sum.get()
        after_overhead_count = sum(b.get() for b in overhead_child._buckets)
        assert after_overhead_sum == before_overhead_sum
        assert after_overhead_count == before_overhead_count
        assert client_child._sum.get() == pytest.approx(before_client_sum + 0.1)
        assert server_child._sum.get() == pytest.approx(before_server_sum + 0.5)

    def test_exceptions_do_not_propagate(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.RANDOM
        with patch.object(
            _client_duration.labels(search_type=search_type.value),
            "observe",
            side_effect=RuntimeError("boom"),
        ):
            # Under test and postcondition.
            # Should not raise.
            observe_opensearch_search(search_type, 0.1, 50)


class TestTrackOpenSearchSearch:
    def test_gauge_increments_and_decrements(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.HYBRID
        before = _searches_in_progress.labels(
            search_type=search_type.value
        )._value.get()

        # Under test.
        with track_opensearch_search(search_type):
            during = _searches_in_progress.labels(
                search_type=search_type.value
            )._value.get()

            # Postcondition.
            assert during == before + 1

        after = _searches_in_progress.labels(search_type=search_type.value)._value.get()
        assert after == before

    def test_gauge_decrements_on_exception(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.SEMANTIC
        before = _searches_in_progress.labels(
            search_type=search_type.value
        )._value.get()

        # Under test.
        raised = False
        try:
            with track_opensearch_search(search_type):
                raise ValueError("simulated search failure")
        except ValueError:
            raised = True

        # Postcondition.
        assert raised

        after = _searches_in_progress.labels(search_type=search_type.value)._value.get()
        assert after == before

    def test_increments_attempt_counter_on_entry(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.HYBRID
        before = _search_total.labels(search_type=search_type.value)._value.get()

        # Under test.
        with track_opensearch_search(search_type):
            during = _search_total.labels(search_type=search_type.value)._value.get()

            # Postcondition.
            assert during == before + 1

        after = _search_total.labels(search_type=search_type.value)._value.get()
        # Counter does not decrement on exit.
        assert after == before + 1

    def test_attempt_counter_increments_even_when_body_raises(self) -> None:
        # Precondition.
        # Failures must still count in the denominator of the failure rate.
        search_type = OpenSearchSearchType.KEYWORD
        before = _search_total.labels(search_type=search_type.value)._value.get()

        # Under test.
        try:
            with track_opensearch_search(search_type):
                raise ValueError("simulated search failure")
        except ValueError:
            pass

        # Postcondition.
        after = _search_total.labels(search_type=search_type.value)._value.get()
        assert after == before + 1

    def test_inc_exception_does_not_break_search(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.RANDOM
        before = _searches_in_progress.labels(
            search_type=search_type.value
        )._value.get()

        # Under test.
        with patch.object(
            _searches_in_progress.labels(search_type=search_type.value),
            "inc",
            side_effect=RuntimeError("boom"),
        ):
            # Context manager should still yield without decrementing.
            with track_opensearch_search(search_type):
                # Search logic would execute here.
                during = _searches_in_progress.labels(
                    search_type=search_type.value
                )._value.get()

                # Postcondition.
                assert during == before

        after = _searches_in_progress.labels(search_type=search_type.value)._value.get()
        assert after == before

    def test_attempt_counter_failure_does_not_break_search(self) -> None:
        # Precondition.
        search_type = OpenSearchSearchType.UNKNOWN

        # Under test and postcondition.
        with patch.object(
            _search_total.labels(search_type=search_type.value),
            "inc",
            side_effect=RuntimeError("boom"),
        ):
            # Context manager should still yield.
            with track_opensearch_search(search_type):
                pass
