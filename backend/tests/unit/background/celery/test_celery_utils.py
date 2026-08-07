"""Unit tests for pruning enumeration metrics.

Enumeration runs in a spawned child process whose Prometheus registry is never
scraped, so metrics are emitted by the pruning parent task: duration via
observe_pruning_enumeration_duration, rate limits via
inc_pruning_rate_limit_error_if_detected on the child's exception text.
"""

from onyx.server.metrics.pruning_metrics import (
    PRUNING_ENUMERATION_DURATION,
    PRUNING_RATE_LIMIT_ERRORS,
    inc_pruning_rate_limit_error_if_detected,
    observe_pruning_enumeration_duration,
)


class TestEnumerationDuration:
    def test_recorded_under_connector_type_label(self) -> None:
        before = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()

        observe_pruning_enumeration_duration(12.5, "google_drive")

        after = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()
        assert after == before + 12.5


class TestRateLimitDetection:
    def test_increments_on_rate_limit_message(self) -> None:
        before = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()

        assert inc_pruning_rate_limit_error_if_detected(
            "rate limit exceeded", "google_drive"
        )

        after = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()
        assert after == before + 1

    def test_increments_on_429_in_message(self) -> None:
        before = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="confluence"
        )._value.get()

        assert inc_pruning_rate_limit_error_if_detected(
            "HTTP 429 Too Many Requests", "confluence"
        )

        after = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="confluence"
        )._value.get()
        assert after == before + 1

    def test_does_not_increment_on_non_rate_limit_error(self) -> None:
        before = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="slack")._value.get()

        assert not inc_pruning_rate_limit_error_if_detected(
            "connection timeout", "slack"
        )

        after = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="slack")._value.get()
        assert after == before

    def test_rate_limit_detection_is_case_insensitive(self) -> None:
        before = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="jira")._value.get()

        assert inc_pruning_rate_limit_error_if_detected("RATE LIMIT exceeded", "jira")

        after = PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="jira")._value.get()
        assert after == before + 1

    def test_connector_type_label_matches_input(self) -> None:
        before_gd = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()
        before_jira = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="jira"
        )._value.get()

        inc_pruning_rate_limit_error_if_detected("rate limit exceeded", "google_drive")

        assert (
            PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="google_drive")._value.get()
            == before_gd + 1
        )
        assert (
            PRUNING_RATE_LIMIT_ERRORS.labels(connector_type="jira")._value.get()
            == before_jira
        )
