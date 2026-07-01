import re
import time
from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import IO
from unittest.mock import patch

import pytest

from onyx.connectors.braintrust.connector import BraintrustCheckpoint
from onyx.connectors.braintrust.connector import BraintrustConnector
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import TabularSection
from onyx.connectors.models import TextSection

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
    "created": "2026-06-08T00:00:00Z",
}
_DATASET_ROW = {
    "id": "row-1",
    "_pagination_key": "p002",
    "created": "2026-06-08T12:00:00Z",
    "input": {"doc": "a.md"},
    "expected": {"result": "merged"},
    "metadata": {"case": "simple"},
}
_EXPERIMENT_ROW = {
    "id": "row-2",
    "_pagination_key": "p001",
    "created": "2026-06-08T13:00:00Z",
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


def _fake_request(
    self: BraintrustConnector,  # noqa: ARG001
    method: str,  # noqa: ARG001
    path: str,
    params: dict[str, Any] | None = None,  # noqa: ARG001
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if path == "/v1/project":
        return {"objects": [_PROJECT]}
    if path == "/v1/prompt":
        return {"objects": [_PROMPT]}
    if path == "/v1/prompt/prompt-1":
        return _PROMPT
    if path == "/v1/dataset":
        return {"objects": [_DATASET]}
    if path == "/v1/experiment":
        return {"objects": [_EXPERIMENT]}
    if path == "/v1/experiment/exp-1/summarize":
        return _SUMMARY
    if path == "/btql":
        query = (json_body or {})["query"]
        if "dataset('ds-1')" in query:
            return {"data": _apply_created_filter(query, [_DATASET_ROW])}
        if "experiment('exp-1')" in query:
            return {"data": _apply_created_filter(query, [_EXPERIMENT_ROW])}
        return {"data": []}
    raise AssertionError(f"unexpected path: {path}")


def _apply_created_filter(
    query: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Mimic the live BTQL endpoint's `created >=/<=` filtering (ISO strings
    compare lexicographically)."""
    lower = re.search(r"created >= '([^']+)'", query)
    upper = re.search(r"created <= '([^']+)'", query)
    out = []
    for row in rows:
        created = row.get("created", "")
        if lower and created < lower.group(1):
            continue
        if upper and created > upper.group(1):
            continue
        out.append(row)
    return out


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


def _docs(outputs: list[Any]) -> dict[str, Document]:
    return {o.id: o for o in outputs if isinstance(o, Document)}


@pytest.fixture
def staged_csvs() -> dict[str, bytes]:
    return {}


@pytest.fixture
def connector(staged_csvs: dict[str, bytes]) -> BraintrustConnector:
    connector = BraintrustConnector(experiment_row_lookback_days=0)
    connector.load_credentials({"braintrust_api_key": "test-key"})

    def raw_file_callback(content: IO[bytes], content_type: str) -> str:
        assert content_type == "text/csv"
        file_id = f"csv-{len(staged_csvs)}"
        staged_csvs[file_id] = content.read()
        return file_id

    connector.set_raw_file_callback(raw_file_callback)
    return connector


def test_full_sweep_produces_prompt_dataset_experiment_docs(
    connector: BraintrustConnector,
) -> None:
    """One pass yields a prompt doc, one dataset doc, and one experiment doc
    with the documented id scheme and no failures."""
    with patch.object(BraintrustConnector, "_request", _fake_request):
        outputs = _run_connector(connector)

    assert set(_docs(outputs)) == {
        "braintrust:prompt:prompt-1",
        "braintrust:ds:ds-1",
        "braintrust:exp:exp-1",
    }
    assert not [o for o in outputs if isinstance(o, ConnectorFailure)]


def test_dataset_doc_has_text_and_tabular_sections(
    connector: BraintrustConnector,
    staged_csvs: dict[str, bytes],
) -> None:
    """The dataset doc carries a prose header section plus a CSV table of all
    rows."""
    with patch.object(BraintrustConnector, "_request", _fake_request):
        doc = _docs(_run_connector(connector))["braintrust:ds:ds-1"]

    text, tabular = doc.sections
    assert isinstance(text, TextSection)
    assert "merge-cases" in (text.text or "")
    assert "1 rows" in (text.text or "")
    assert isinstance(tabular, TabularSection)
    assert doc.file_id == tabular.csv_file_id
    header, row = staged_csvs[tabular.csv_file_id].decode("utf-8").strip().split("\n")
    assert header == "id,created,input,expected,metadata,tags"
    assert row.startswith("row-1,")
    assert '""doc"": ""a.md""' in row


def test_experiment_doc_combines_summary_and_score_table(
    connector: BraintrustConnector,
    staged_csvs: dict[str, bytes],
) -> None:
    """The experiment doc leads with the prose score summary and includes a
    table with one flattened column per score."""
    with patch.object(BraintrustConnector, "_request", _fake_request):
        doc = _docs(_run_connector(connector))["braintrust:exp:exp-1"]

    text, tabular = doc.sections
    assert isinstance(text, TextSection)
    body = text.text or ""
    assert "correctness 0.9" in body
    assert "merge-run-41" in body
    assert "+0.05" in body
    assert "3 improvements / 1 regressions" in body
    assert isinstance(tabular, TabularSection)
    assert doc.file_id == tabular.csv_file_id
    header, row = staged_csvs[tabular.csv_file_id].decode("utf-8").strip().split("\n")
    assert header == "id,created,input,output,expected,correctness"
    assert row.startswith("row-2,") and row.endswith(",0.9")
    assert tabular.link == _SUMMARY["experiment_url"]


def test_unchanged_dataset_not_reindexed(connector: BraintrustConnector) -> None:
    """A dataset with no rows created inside [start, end] is probed but not
    rebuilt, so its existing doc is left untouched."""
    window_start = time.mktime(time.strptime("2026-06-09", "%Y-%m-%d"))
    with patch.object(BraintrustConnector, "_request", _fake_request):
        outputs = _run_connector(connector, start=window_start)

    assert "braintrust:ds:ds-1" not in _docs(outputs)


def test_experiment_outside_window_not_reindexed(
    connector: BraintrustConnector,
) -> None:
    """Experiments are write-once: one created before the poll window is not
    re-emitted (its previously indexed doc stands)."""
    window_start = time.mktime(time.strptime("2026-06-09", "%Y-%m-%d"))
    with patch.object(BraintrustConnector, "_request", _fake_request):
        outputs = _run_connector(connector, start=window_start)

    assert "braintrust:exp:exp-1" not in _docs(outputs)


def test_lookback_drops_table_but_keeps_summary() -> None:
    """An in-window experiment older than the lookback window gets a
    summary-only doc with no table section."""
    connector = BraintrustConnector(experiment_row_lookback_days=30)
    connector.load_credentials({"braintrust_api_key": "test-key"})
    old_created = (datetime.now(tz=timezone.utc) - timedelta(days=60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    def request_with_old_experiment(
        self: BraintrustConnector,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path == "/v1/experiment":
            return {"objects": [{**_EXPERIMENT, "created": old_created}]}
        return _fake_request(self, method, path, params, json_body)

    with patch.object(BraintrustConnector, "_request", request_with_old_experiment):
        doc = _docs(_run_connector(connector))["braintrust:exp:exp-1"]

    assert len(doc.sections) == 1
    assert isinstance(doc.sections[0], TextSection)
    assert "correctness 0.9" in (doc.sections[0].text or "")


def test_btql_keyset_pagination_accumulates_table(
    staged_csvs: dict[str, bytes],
) -> None:
    """Full pages chain via `_pagination_key <` filters until a short page."""
    connector = BraintrustConnector(experiment_row_lookback_days=0)
    connector.load_credentials({"braintrust_api_key": "test-key"})

    def raw_file_callback(content: IO[bytes], content_type: str) -> str:
        assert content_type == "text/csv"
        file_id = f"csv-{len(staged_csvs)}"
        staged_csvs[file_id] = content.read()
        return file_id

    connector.set_raw_file_callback(raw_file_callback)
    page1 = [
        {**_DATASET_ROW, "id": f"row-{i}", "_pagination_key": f"p{900 - i}"}
        for i in range(500)
    ]
    page2 = [{**_DATASET_ROW, "id": "row-last", "_pagination_key": "p100"}]
    seen_filters: list[str] = []

    def paged_request(
        self: BraintrustConnector,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path == "/btql" and "dataset('ds-1')" in (json_body or {})["query"]:
            query = (json_body or {})["query"]
            if "select: id" in query:
                return {"data": [{"id": "row-1"}]}
            seen_filters.append(query)
            return {"data": page2 if "_pagination_key <" in query else page1}
        return _fake_request(self, method, path, params, json_body)

    with patch.object(BraintrustConnector, "_request", paged_request):
        doc = _docs(_run_connector(connector))["braintrust:ds:ds-1"]

    tabular = doc.sections[1]
    assert isinstance(tabular, TabularSection)
    assert doc.file_id == tabular.csv_file_id
    assert (
        len(staged_csvs[tabular.csv_file_id].decode("utf-8").strip().split("\n"))
        == 1 + 501
    )
    assert len(seen_filters) == 2
    assert "_pagination_key < 'p401'" in seen_filters[1]


def test_object_failure_isolated_and_sweep_continues(
    connector: BraintrustConnector,
) -> None:
    """A dataset whose row fetch fails yields an EntityFailure while prompts
    and experiments still index."""

    def request_with_dead_dataset(
        self: BraintrustConnector,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path == "/btql" and "dataset('ds-1')" in (json_body or {})["query"]:
            if "select: *" in (json_body or {})["query"]:
                raise RuntimeError("404 Not Found")
            return {"data": [{"id": "row-1"}]}
        return _fake_request(self, method, path, params, json_body)

    with patch.object(BraintrustConnector, "_request", request_with_dead_dataset):
        outputs = _run_connector(connector)

    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == "ds-1"
    assert "braintrust:exp:exp-1" in _docs(outputs)
    assert "braintrust:prompt:prompt-1" in _docs(outputs)


def test_none_lookback_falls_back_to_default() -> None:
    """A cleared optional UI field arrives as None and must not break the
    `> 0` comparison; it resolves to the default window."""
    connector = BraintrustConnector(experiment_row_lookback_days=None)
    assert connector._experiment_row_lookback_days == 30


def test_checkpoint_roundtrip(connector: BraintrustConnector) -> None:
    """Checkpoints serialize and restore across phases."""
    checkpoint = connector.build_dummy_checkpoint()
    restored = connector.validate_checkpoint_json(checkpoint.model_dump_json())
    assert restored == checkpoint
    assert isinstance(restored, BraintrustCheckpoint)
