"""Tests for pruning-specific Prometheus metrics."""

import pytest

from onyx.server.metrics.pruning_metrics import inc_pruning_rate_limit_error
from onyx.server.metrics.pruning_metrics import observe_pruning_diff_duration
from onyx.server.metrics.pruning_metrics import observe_pruning_enumeration_duration
from onyx.server.metrics.pruning_metrics import PRUNING_DIFF_DURATION
from onyx.server.metrics.pruning_metrics import PRUNING_ENUMERATION_DURATION
from onyx.server.metrics.pruning_metrics import PRUNING_RATE_LIMIT_ERRORS


class TestObservePruningEnumerationDuration:
    def test_observes_duration(self) -> None:
        before = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()

        observe_pruning_enumeration_duration(10.0, "google_drive")

        after = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()
        assert after == pytest.approx(before + 10.0)

    def test_labels_by_connector_type(self) -> None:
        before_gd = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()
        before_conf = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="confluence"
        )._sum.get()

        observe_pruning_enumeration_duration(5.0, "google_drive")

        after_gd = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()
        after_conf = PRUNING_ENUMERATION_DURATION.labels(
            connector_type="confluence"
        )._sum.get()

        assert after_gd == pytest.approx(before_gd + 5.0)
        assert after_conf == pytest.approx(before_conf)

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            PRUNING_ENUMERATION_DURATION,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        observe_pruning_enumeration_duration(1.0, "google_drive")


class TestObservePruningDiffDuration:
    def test_observes_duration(self) -> None:
        before = PRUNING_DIFF_DURATION.labels(connector_type="confluence")._sum.get()

        observe_pruning_diff_duration(3.0, "confluence")

        after = PRUNING_DIFF_DURATION.labels(connector_type="confluence")._sum.get()
        assert after == pytest.approx(before + 3.0)

    def test_labels_by_connector_type(self) -> None:
        before_conf = PRUNING_DIFF_DURATION.labels(
            connector_type="confluence"
        )._sum.get()
        before_slack = PRUNING_DIFF_DURATION.labels(connector_type="slack")._sum.get()

        observe_pruning_diff_duration(2.0, "confluence")

        after_conf = PRUNING_DIFF_DURATION.labels(
            connector_type="confluence"
        )._sum.get()
        after_slack = PRUNING_DIFF_DURATION.labels(connector_type="slack")._sum.get()

        assert after_conf == pytest.approx(before_conf + 2.0)
        assert after_slack == pytest.approx(before_slack)

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            PRUNING_DIFF_DURATION,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        observe_pruning_diff_duration(1.0, "confluence")


class TestIncPruningRateLimitError:
    def test_increments_counter(self) -> None:
        before = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()

        inc_pruning_rate_limit_error("google_drive")

        after = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()
        assert after == before + 1

    def test_labels_by_connector_type(self) -> None:
        before_gd = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()
        before_jira = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="jira"
        )._value.get()

        inc_pruning_rate_limit_error("google_drive")

        after_gd = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="google_drive"
        )._value.get()
        after_jira = PRUNING_RATE_LIMIT_ERRORS.labels(
            connector_type="jira"
        )._value.get()

        assert after_gd == before_gd + 1
        assert after_jira == before_jira

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            PRUNING_RATE_LIMIT_ERRORS,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_pruning_rate_limit_error("google_drive")
