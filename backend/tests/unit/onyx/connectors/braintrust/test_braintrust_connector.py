import time
from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from unittest.mock import patch

import pytest
import requests

from onyx.connectors.braintrust.connector import BraintrustCheckpoint
from onyx.connectors.braintrust.connector import BraintrustConnector
from onyx.connectors.braintrust.connector import BraintrustObjectRef
from onyx.connectors.braintrust.connector import BraintrustPhase
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode

_PROJECT = {"id": "proj-1", "name": "agent-wiki"}
_PROMPT = {
    "id": "prompt-1",
    "name": "merge-prompt",
    "project_id": "proj-1",
    "slug": "merge-prompt",
    "description": "Resolves merge conflicts",
    "created": "2026-06-01T00:00:00Z",
    "prompt_data": {
        "options": {"model": "gpt-5"},
        "prompt": {
            "messages": [{"role": "system", "content": "You resolve conflicts."}]
        },
    },
}
_DATASET = {
    "id": "ds-1",
    "name": "merge-cases",
    "project_id": "proj-1",
    "created": "2026-06-01T00:00:00Z",
}
_EXPERIMENT = {
    "id": "exp-1",
    "name": "merge-run-42",
    "project_id": "proj-1",
    "base_exp_id": "exp-0",
    "created": "2026-06-02T00:00:00Z",
}
_DATASET_EVENT = {
    "id": "row-1",
    "created": "2026-06-02T12:00:00Z",
    "input": {"doc": "a.md"},
    "expected": {"result": "merged"},
    "metadata": {"case": "simple"},
}
_EXPERIMENT_EVENT = {
    "id": "row-2",
    "created": "2026-06-02T13:00:00Z",
    "input": {"doc": "b.md"},
    "output": {"result": "merged"},
    "expected": {"result": "merged"},
    "scores": {"correctness": 0.9},
}
_SUMMARY = {
    "experiment_url": "https://www.braintrust.dev/app/o/p/agent-wiki/experiments/merge-run-42",
    "comparison_experiment_name": "merge-run-41",
    "scores": {
        "correctness": {
            "name": "correctness",
            "score": 0.9,
            "diff": 0.05,
            "improvements": 3,
            "regressions": 1,
        }
    },
    "metrics": {"duration": {"name": "duration", "metric": 2.5, "unit": "s"}},
}


def _fake_get(
    self: BraintrustConnector,  # noqa: ARG001
    path: str,
    params: dict[str, Any] | None = None,  # noqa: ARG001
) -> dict[str, Any]:
    if path == "/v1/project":
        return {"objects": [_PROJECT]}
    if path == "/v1/prompt":
        return {"objects": [_PROMPT]}
    if path == "/v1/prompt/prompt-1":
        return _PROMPT
    if path == "/v1/dataset":
        return {"objects": [_DATASET]}
    if path == "/v1/dataset/ds-1/fetch":
        return {"events": [_DATASET_EVENT], "cursor": None}
    if path == "/v1/experiment":
        return {"objects": [_EXPERIMENT]}
    if path == "/v1/experiment/exp-1/fetch":
        return {"events": [_EXPERIMENT_EVENT], "cursor": None}
    if path == "/v1/experiment/exp-1/summarize":
        return _SUMMARY
    raise AssertionError(f"unexpected path: {path}")


def _run_connector(
    connector: BraintrustConnector,
    start: float = 0,
    end: float | None = None,
) -> list[Document | HierarchyNode | ConnectorFailure]:
    end = end if end is not None else time.time()
    outputs: list[Document | HierarchyNode | ConnectorFailure] = []
    checkpoint = connector.build_dummy_checkpoint()
    for _ in range(100):
        generator: Iterator[Any] = connector.load_from_checkpoint(
            start, end, checkpoint
        )
        while True:
            try:
                outputs.append(next(generator))
            except StopIteration as e:
                checkpoint = e.value
                break
        if not checkpoint.has_more:
            return outputs
    raise AssertionError("connector never finished")


@pytest.fixture
def connector() -> BraintrustConnector:
    connector = BraintrustConnector(experiment_row_lookback_days=0)
    connector.load_credentials({"braintrust_api_key": "test-key"})
    return connector


def test_none_lookback_falls_back_to_default() -> None:
    """A cleared optional UI field arrives as None and must not break the
    `> 0` comparison; it resolves to the default window."""
    connector = BraintrustConnector(experiment_row_lookback_days=None)
    assert connector._experiment_row_lookback_days == 30


def test_out_of_window_pages_skipped_within_one_call(
    connector: BraintrustConnector,
) -> None:
    """Pages whose events all fall outside [start, end] are skipped inside a
    single load_from_checkpoint call instead of costing one checkpoint
    round-trip each."""
    old_event = {**_DATASET_EVENT, "created": "2020-01-01T00:00:00Z"}
    pages = {
        None: ([old_event], "c1"),
        "c1": ([old_event], "c2"),
        "c2": ([_DATASET_EVENT], None),
    }
    fetch_calls: list[str | None] = []

    def get_paged(
        self: BraintrustConnector, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path == "/v1/dataset/ds-1/fetch":
            cursor = (params or {}).get("cursor")
            fetch_calls.append(cursor)
            events, next_cursor = pages[cursor]
            return {"events": events, "cursor": next_cursor}
        return _fake_get(self, path, params)

    checkpoint = BraintrustCheckpoint(
        has_more=True,
        phase=BraintrustPhase.DATASET_ROWS,
        todo=[BraintrustObjectRef(id="ds-1", name="merge-cases")],
    )
    window_start = time.mktime(time.strptime("2026-06-01", "%Y-%m-%d"))

    with patch.object(BraintrustConnector, "_get", get_paged):
        outputs = list(
            connector.load_from_checkpoint(window_start, time.time(), checkpoint)
        )

    assert fetch_calls == [None, "c1", "c2"]
    assert sum(1 for o in outputs if isinstance(o, Document)) == 1


def test_project_and_experiment_lists_fetched_once(
    connector: BraintrustConnector,
) -> None:
    """Project names and the experiment list are cached on the instance, not
    re-listed by every phase seed."""
    list_calls: list[str] = []

    def counting_get(
        self: BraintrustConnector, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path in ("/v1/project", "/v1/experiment"):
            list_calls.append(path)
        return _fake_get(self, path, params)

    with patch.object(BraintrustConnector, "_get", counting_get):
        _run_connector(connector)

    assert list_calls.count("/v1/project") == 1
    assert list_calls.count("/v1/experiment") == 1


def test_fetch_error_skips_object_and_sweep_continues(
    connector: BraintrustConnector,
) -> None:
    """A non-transient fetch error (e.g. object deleted upstream -> 404) yields
    an EntityFailure and pops the object so the sweep and later phases still
    complete."""

    def get_with_dead_dataset(
        self: BraintrustConnector, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path == "/v1/dataset/ds-1/fetch":
            raise requests.HTTPError("404 Client Error: Not Found")
        return _fake_get(self, path, params)

    with patch.object(BraintrustConnector, "_get", get_with_dead_dataset):
        outputs = _run_connector(connector)

    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == "ds-1"
    ids = {o.id for o in outputs if isinstance(o, Document)}
    assert "braintrust:exp:exp-1" in ids
    assert "braintrust:exp:exp-1:row:row-2" in ids


def test_experiment_row_lookback_skips_old_experiments() -> None:
    """Experiments older than the lookback window keep their summary doc but
    contribute no per-row docs."""
    connector = BraintrustConnector(experiment_row_lookback_days=30)
    connector.load_credentials({"braintrust_api_key": "test-key"})
    old_created = (datetime.now(tz=timezone.utc) - timedelta(days=60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    def get_with_old_experiment(
        self: BraintrustConnector, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path == "/v1/experiment":
            return {"objects": [{**_EXPERIMENT, "created": old_created}]}
        return _fake_get(self, path, params)

    with patch.object(BraintrustConnector, "_get", get_with_old_experiment):
        outputs = _run_connector(connector)

    ids = {o.id for o in outputs if isinstance(o, Document)}
    assert "braintrust:exp:exp-1" in ids
    assert not any(":row:row-2" in doc_id for doc_id in ids)


def test_full_sweep_produces_all_doc_types(connector: BraintrustConnector) -> None:
    """One pass over a small org yields prompt, dataset-row, experiment-summary,
    and experiment-row documents with the documented id scheme."""
    with patch.object(BraintrustConnector, "_get", _fake_get):
        outputs = _run_connector(connector)

    docs = [o for o in outputs if isinstance(o, Document)]
    ids = {doc.id for doc in docs}
    assert ids == {
        "braintrust:prompt:prompt-1",
        "braintrust:ds:ds-1:row:row-1",
        "braintrust:exp:exp-1",
        "braintrust:exp:exp-1:row:row-2",
    }
    assert not [o for o in outputs if isinstance(o, ConnectorFailure)]


def test_time_window_filters_event_rows(connector: BraintrustConnector) -> None:
    """Events created outside [start, end] are skipped; low-volume prompts and
    experiment summaries are always refreshed."""
    window_start = time.mktime(time.strptime("2026-06-03", "%Y-%m-%d"))
    with patch.object(BraintrustConnector, "_get", _fake_get):
        outputs = _run_connector(connector, start=window_start)

    docs = [o for o in outputs if isinstance(o, Document)]
    ids = {doc.id for doc in docs}
    assert ids == {
        "braintrust:prompt:prompt-1",
        "braintrust:exp:exp-1",
    }


def test_experiment_summary_is_prose_with_scores(
    connector: BraintrustConnector,
) -> None:
    """The experiment-summary body reads as prose containing aggregate scores,
    baseline deltas, and regression counts."""
    with patch.object(BraintrustConnector, "_get", _fake_get):
        outputs = _run_connector(connector)

    summary = next(
        o for o in outputs if isinstance(o, Document) and o.id == "braintrust:exp:exp-1"
    )
    text = summary.sections[0].text or ""
    assert "Experiment 'merge-run-42'" in text
    assert "correctness 0.9" in text
    assert "merge-run-41" in text
    assert "+0.05" in text
    assert "3 improvements / 1 regressions" in text
    assert summary.sections[0].link == _SUMMARY["experiment_url"]


def test_malformed_event_yields_connector_failure(
    connector: BraintrustConnector,
) -> None:
    """A row that fails mapping becomes a ConnectorFailure with a populated
    DocumentFailure instead of aborting the sweep."""

    def get_with_bad_event(
        self: BraintrustConnector, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path == "/v1/dataset/ds-1/fetch":
            return {"events": [{"created": "2026-06-02T12:00:00Z"}], "cursor": None}
        return _fake_get(self, path, params)

    with patch.object(BraintrustConnector, "_get", get_with_bad_event):
        outputs = _run_connector(connector)

    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    docs = [o for o in outputs if isinstance(o, Document)]
    assert {doc.id for doc in docs} == {
        "braintrust:prompt:prompt-1",
        "braintrust:exp:exp-1",
        "braintrust:exp:exp-1:row:row-2",
    }


def test_checkpoint_resumes_mid_phase(connector: BraintrustConnector) -> None:
    """A checkpoint serialized mid-sweep resumes from its cursor instead of
    restarting the phase."""
    checkpoint = BraintrustCheckpoint(
        has_more=True,
        phase=BraintrustPhase.DATASET_ROWS,
        todo=[
            BraintrustObjectRef(
                id="ds-1",
                name="merge-cases",
                project_id="proj-1",
                project_name="agent-wiki",
            )
        ],
        cursor="cursor-abc",
    )
    seen_cursors: list[str | None] = []

    def get_tracking_cursor(
        self: BraintrustConnector, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path == "/v1/dataset/ds-1/fetch":
            seen_cursors.append((params or {}).get("cursor"))
            return {"events": [_DATASET_EVENT], "cursor": None}
        return _fake_get(self, path, params)

    restored = connector.validate_checkpoint_json(checkpoint.model_dump_json())
    assert restored.cursor == "cursor-abc"

    with patch.object(BraintrustConnector, "_get", get_tracking_cursor):
        generator = connector.load_from_checkpoint(0, time.time(), restored)
        outputs = list(generator)

    assert seen_cursors == ["cursor-abc"]
    assert any(
        isinstance(o, Document) and o.id == "braintrust:ds:ds-1:row:row-1"
        for o in outputs
    )
