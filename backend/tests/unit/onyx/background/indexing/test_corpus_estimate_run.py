"""The docfetching corpus count runs beside the fetch and reports every
outcome to fleet telemetry: the count, a stopped count as a lower bound, and
a failed count as no estimate."""

import threading
import time
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.background.indexing import run_docfetching
from onyx.background.indexing.run_docfetching import _CorpusEstimateRun
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    CorpusEstimateConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import CorpusEstimate, DocumentTypeLabel

START = datetime(2024, 6, 1, tzinfo=timezone.utc)
END = datetime(2024, 6, 2, tzinfo=timezone.utc)


class _Counter(CorpusEstimateConnector):
    """Counts three documents, or waits to be stopped, or fails."""

    def __init__(self, outcome: str) -> None:
        self._outcome = outcome
        self.windows: list[tuple[float, float]] = []
        self.started = threading.Event()

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        return credentials

    def estimate_corpus(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        should_stop: Callable[[], bool],
        on_progress: Callable[[CorpusEstimate], None],
    ) -> CorpusEstimate:
        self.windows.append((start, end))
        self.started.set()
        if self._outcome == "failed":
            raise RuntimeError("PRIVATE listing failure")
        if self._outcome == "waits":
            while not should_stop():
                time.sleep(0.01)
            return CorpusEstimate(total_docs=1, partial=True)
        on_progress(CorpusEstimate(total_docs=1, partial=True))
        return CorpusEstimate(total_docs=3, docs_by_type={DocumentTypeLabel.PDF: 3})


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr(run_docfetching, "time_stage", lambda *_: nullcontext())
    monkeypatch.setattr(
        run_docfetching, "get_session_with_current_tenant", lambda: nullcontext()
    )
    emitted = Mock()
    monkeypatch.setattr(run_docfetching, "emit_corpus_estimate", emitted)
    return emitted


def _start(connector: _Counter) -> _CorpusEstimateRun:
    return _CorpusEstimateRun(
        lambda _session: connector, 7, 3, DocumentSource.GOOGLE_DRIVE, START, END
    )


def _broken_builder(_session: object) -> _Counter:
    raise RuntimeError("PRIVATE credential failure")


def test_the_count_reports_its_window_and_estimate(sink: Mock) -> None:
    connector = _Counter("counted")
    _start(connector).wait(5)

    assert connector.windows == [(START.timestamp(), END.timestamp())]
    assert sink.call_count == 1
    assert sink.call_args.args == (7, 3, "google_drive")
    assert sink.call_args.kwargs["estimate"] == CorpusEstimate(
        total_docs=3, docs_by_type={DocumentTypeLabel.PDF: 3}
    )
    assert sink.call_args.kwargs["window_start"] == START.timestamp()
    assert sink.call_args.kwargs["window_end"] == END.timestamp()


def test_a_failed_count_reports_no_estimate(sink: Mock) -> None:
    _start(_Counter("failed")).wait(5)

    assert sink.call_count == 1
    assert sink.call_args.kwargs["estimate"] is None


def test_a_connector_that_cannot_be_built_reports_no_estimate(sink: Mock) -> None:
    run = _CorpusEstimateRun(
        _broken_builder, 7, 3, DocumentSource.GOOGLE_DRIVE, START, END
    )
    run.wait(5)

    assert sink.call_count == 1
    assert sink.call_args.kwargs["estimate"] is None


def test_a_stop_ends_the_count_with_a_lower_bound(sink: Mock) -> None:
    connector = _Counter("waits")
    run = _start(connector)
    assert connector.started.wait(timeout=5)

    run.stop()
    run.wait(5)

    assert sink.call_args.kwargs["estimate"] == CorpusEstimate(
        total_docs=1, partial=True
    )
