import copy
import csv
import io
import json
from collections.abc import Callable
from collections.abc import Mapping
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from enum import Enum
from typing import Any

import requests
from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rate_limit_builder
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    wrap_request_to_handle_ratelimiting,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import TabularSection
from onyx.connectors.models import TextSection
from onyx.utils.retry_wrapper import retry_builder

_BASE_URL = "https://api.braintrust.dev"
_API_KEY = "braintrust_api_key"
_TIMEOUT = 60
_NUM_RETRIES = 5
_MAX_CALLS_PER_SECOND = 4
_LIST_PAGE_SIZE = 100
_BTQL_PAGE_SIZE = 500
_MAX_TABLE_ROWS = 10_000
_SUMMARIES_PER_CALL = 5
_PROMPTS_PER_CALL = 50
# Nightly eval runs create a whole new experiment each time, so unbounded
# per-run tables grow with time, not suite size. 0 disables the cutoff.
_DEFAULT_EXPERIMENT_ROW_LOOKBACK_DAYS = 30

_DATASET_COLUMNS = ["id", "created", "input", "expected", "metadata", "tags"]
_EXPERIMENT_BASE_COLUMNS = ["id", "created", "input", "output", "expected"]


class _TransientServerError(Exception):
    pass


class BraintrustPhase(str, Enum):
    PROMPTS = "prompts"
    DATASETS = "datasets"
    EXPERIMENTS = "experiments"
    DONE = "done"


_PHASE_ORDER = [
    BraintrustPhase.PROMPTS,
    BraintrustPhase.DATASETS,
    BraintrustPhase.EXPERIMENTS,
    BraintrustPhase.DONE,
]


class BraintrustObjectRef(BaseModel):
    id: str
    name: str
    project_id: str | None = None
    project_name: str | None = None
    base_exp_id: str | None = None
    created: str | None = None


class BraintrustCheckpoint(ConnectorCheckpoint):
    phase: BraintrustPhase = BraintrustPhase.PROMPTS
    todo: list[BraintrustObjectRef] | None = None


def _parse_time(time_str: str | None) -> datetime | None:
    if not time_str:
        return None
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _render_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str, ensure_ascii=False)


def _coerce_metadata(values: Mapping[str, Any]) -> dict[str, str | list[str]]:
    return {k: _render_value(v) for k, v in values.items() if v not in (None, "", {})}


def _rows_to_csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_render_value(row.get(col)) for col in columns])
    return out.getvalue().rstrip("\n")


def _score_columns(rows: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        names.update((row.get("scores") or {}).keys())
    return sorted(names)


class BraintrustConnector(CheckpointedConnector[BraintrustCheckpoint]):
    def __init__(
        self,
        project_name: str | None = None,
        experiment_row_lookback_days: int | None = None,
    ) -> None:
        self._project_name = project_name
        self._experiment_row_lookback_days = (
            _DEFAULT_EXPERIMENT_ROW_LOOKBACK_DAYS
            if experiment_row_lookback_days is None
            else experiment_row_lookback_days
        )
        self._api_key: str | None = None
        self._rate_limited_request: Callable[..., requests.Response] | None = None
        self._project_names: dict[str, str] | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        api_key = credentials.get(_API_KEY)
        if not api_key or not isinstance(api_key, str):
            raise ConnectorMissingCredentialError("Braintrust")
        self._api_key = api_key
        return None

    @retry_builder(
        tries=_NUM_RETRIES,
        delay=1,
        exceptions=(
            requests.ConnectionError,
            requests.Timeout,
            _TransientServerError,
        ),
    )
    @rate_limit_builder(max_calls=_MAX_CALLS_PER_SECOND, period=1)
    def _raw_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        response = requests.request(
            method,
            f"{_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            params={k: v for k, v in (params or {}).items() if v is not None},
            json=json_body,
            timeout=_TIMEOUT,
        )
        if response.status_code in (500, 502, 503, 504):
            raise _TransientServerError(
                f"Braintrust API returned {response.status_code} for {path}"
            )
        return response

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise ConnectorMissingCredentialError("Braintrust")
        if self._rate_limited_request is None:
            self._rate_limited_request = wrap_request_to_handle_ratelimiting(
                self._raw_request
            )
        response = self._rate_limited_request(method, path, params, json_body)
        if response.status_code in (401, 403):
            raise CredentialInvalidError(
                f"Braintrust API rejected the API key ({response.status_code})"
            )
        response.raise_for_status()
        return response.json()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def _btql_rows(
        self,
        source: str,
        object_id: str,
        start_dt: datetime | None = None,
        end_dt: datetime | None = None,
        max_rows: int = _MAX_TABLE_ROWS,
    ) -> list[dict[str, Any]]:
        """Fetch event rows via BTQL with the time window pushed server-side.

        The fetch endpoints silently ignore a `filter` body field, so BTQL is
        the only honest server-side filter. Pages by keyset on
        `_pagination_key` (stable, time-ordered, returned on every row).
        """
        filters = []
        if start_dt is not None:
            filters.append(f"created >= '{start_dt.isoformat()}'")
        if end_dt is not None:
            filters.append(f"created <= '{end_dt.isoformat()}'")

        rows: list[dict[str, Any]] = []
        last_key: str | None = None
        while len(rows) < max_rows:
            page_filters = list(filters)
            if last_key is not None:
                page_filters.append(f"_pagination_key < '{last_key}'")
            filter_clause = (
                f" | filter: {' and '.join(page_filters)}" if page_filters else ""
            )
            query = (
                f"select: * | from: {source}('{object_id}')"
                f"{filter_clause} | sort: _pagination_key desc"
                f" | limit: {_BTQL_PAGE_SIZE}"
            )
            data = self._request(
                "POST", "/btql", json_body={"query": query, "fmt": "json"}
            )
            page = data.get("data", [])
            rows.extend(page)
            if len(page) < _BTQL_PAGE_SIZE:
                break
            last_key = page[-1]["_pagination_key"]
        return rows[:max_rows]

    def _has_rows_in_window(
        self, source: str, object_id: str, start_dt: datetime, end_dt: datetime
    ) -> bool:
        query = (
            f"select: id | from: {source}('{object_id}')"
            f" | filter: created >= '{start_dt.isoformat()}'"
            f" and created <= '{end_dt.isoformat()}' | limit: 1"
        )
        data = self._request("POST", "/btql", json_body={"query": query, "fmt": "json"})
        return bool(data.get("data"))

    def _list_objects(self, object_path: str) -> list[dict[str, Any]]:
        objects: list[dict[str, Any]] = []
        starting_after: str | None = None
        while True:
            data = self._get(
                f"/v1/{object_path}",
                params={
                    "limit": _LIST_PAGE_SIZE,
                    "starting_after": starting_after,
                    "project_name": self._project_name,
                },
            )
            page = data.get("objects", [])
            objects.extend(page)
            if len(page) < _LIST_PAGE_SIZE:
                return objects
            starting_after = page[-1]["id"]

    def _project_names_by_id(self) -> dict[str, str]:
        if self._project_names is None:
            self._project_names = {
                project["id"]: project.get("name", "")
                for project in self._list_objects("project")
            }
        return self._project_names

    def _to_refs(self, objects: list[dict[str, Any]]) -> list[BraintrustObjectRef]:
        project_names = self._project_names_by_id()
        return [
            BraintrustObjectRef(
                id=obj["id"],
                name=obj.get("name", obj["id"]),
                project_id=obj.get("project_id"),
                project_name=project_names.get(obj.get("project_id") or "", None),
                base_exp_id=obj.get("base_exp_id"),
                created=obj.get("created"),
            )
            for obj in objects
        ]

    def _stage_csv(self, csv_text: str) -> str | None:
        if self.raw_file_callback is None:
            return None
        return self.raw_file_callback(io.BytesIO(csv_text.encode("utf-8")), "text/csv")

    def _prompt_to_document(
        self, prompt: dict[str, Any], project_name: str
    ) -> Document:
        prompt_data = prompt.get("prompt_data") or {}
        options = prompt_data.get("options") or {}
        prompt_block = prompt_data.get("prompt") or {}
        messages = prompt_block.get("messages") or []
        message_text = "\n".join(
            f"[{message.get('role', 'message')}] {_render_value(message.get('content'))}"
            for message in messages
        )
        if not message_text:
            message_text = _render_value(prompt_block.get("content"))

        name = prompt.get("name", prompt["id"])
        lines = [f"Prompt '{name}' in project {project_name}."]
        if prompt.get("description"):
            lines.append(f"Description: {prompt['description']}")
        if options.get("model"):
            lines.append(f"Model: {options['model']}")
        if message_text:
            lines.append(f"Template:\n{message_text}")

        return Document(
            id=f"braintrust:prompt:{prompt['id']}",
            source=DocumentSource.BRAINTRUST,
            title=f"Braintrust prompt: {name}",
            semantic_identifier=f"Prompt: {name}",
            sections=[TextSection(text="\n".join(lines))],
            metadata=_coerce_metadata(
                {
                    "object_type": "prompt",
                    "project": project_name,
                    "model": options.get("model"),
                    "slug": prompt.get("slug"),
                }
            ),
            doc_updated_at=_parse_time(prompt.get("created")),
        )

    def _dataset_to_document(
        self, ref: BraintrustObjectRef, rows: list[dict[str, Any]]
    ) -> Document:
        lines = [
            f"Braintrust dataset '{ref.name}' in project {ref.project_name}"
            f" with {len(rows)} rows of eval cases (input and expected output per case)."
        ]
        if len(rows) >= _MAX_TABLE_ROWS:
            lines.append(f"Table truncated to the {_MAX_TABLE_ROWS} most recent rows.")
        csv_text = _rows_to_csv(_DATASET_COLUMNS, rows)
        return Document(
            id=f"braintrust:ds:{ref.id}",
            source=DocumentSource.BRAINTRUST,
            title=f"Braintrust dataset: {ref.name}",
            semantic_identifier=f"Dataset: {ref.name}",
            sections=[
                TextSection(text="\n".join(lines)),
                TabularSection(text=csv_text, link=""),
            ],
            metadata=_coerce_metadata(
                {
                    "object_type": "dataset",
                    "project": ref.project_name,
                    "dataset": ref.name,
                    "row_count": len(rows),
                }
            ),
            doc_updated_at=_parse_time(ref.created),
            file_id=self._stage_csv(csv_text),
        )

    def _experiment_summary_lines(
        self, ref: BraintrustObjectRef, summary: dict[str, Any]
    ) -> list[str]:
        lines = [f"Experiment '{ref.name}' in project {ref.project_name}."]
        comparison_name = summary.get("comparison_experiment_name")

        score_parts = []
        delta_parts = []
        for score_name, score_info in (summary.get("scores") or {}).items():
            score_value = score_info.get("score")
            if score_value is not None:
                score_parts.append(f"{score_name} {round(float(score_value), 4)}")
            diff = score_info.get("diff")
            improvements = score_info.get("improvements")
            regressions = score_info.get("regressions")
            if diff is not None:
                delta = f"{score_name} {'+' if float(diff) >= 0 else ''}{round(float(diff), 4)}"
                if improvements is not None or regressions is not None:
                    delta += f" ({improvements or 0} improvements / {regressions or 0} regressions)"
                delta_parts.append(delta)
        if score_parts:
            lines.append(f"Scores: {', '.join(score_parts)}.")
        if delta_parts:
            lines.append(
                f"Versus {comparison_name or 'baseline'}: {', '.join(delta_parts)}."
            )

        metric_parts = []
        for metric_name, metric_info in (summary.get("metrics") or {}).items():
            metric_value = metric_info.get("metric")
            if metric_value is not None:
                unit = metric_info.get("unit", "")
                metric_parts.append(
                    f"{metric_name} {round(float(metric_value), 4)}{unit}"
                )
        if metric_parts:
            lines.append(f"Metrics: {', '.join(metric_parts)}.")
        if not score_parts and not metric_parts:
            lines.append("No score or metric summary is available for this experiment.")
        return lines

    def _experiment_to_document(
        self, ref: BraintrustObjectRef, include_table: bool
    ) -> Document:
        params: dict[str, Any] = {"summarize_scores": True}
        if ref.base_exp_id:
            params["comparison_experiment_id"] = ref.base_exp_id
        summary = self._get(f"/v1/experiment/{ref.id}/summarize", params=params)
        lines = self._experiment_summary_lines(ref, summary)

        sections: list[TextSection | TabularSection] = []
        file_id: str | None = None
        if include_table:
            rows = self._btql_rows("experiment", ref.id)
            score_cols = _score_columns(rows)
            flat_rows = [
                {
                    **row,
                    **{
                        name: (row.get("scores") or {}).get(name) for name in score_cols
                    },
                }
                for row in rows
            ]
            columns = _EXPERIMENT_BASE_COLUMNS + score_cols
            lines.append(f"Per-case results table: {len(rows)} rows.")
            if len(rows) >= _MAX_TABLE_ROWS:
                lines.append(
                    f"Table truncated to the {_MAX_TABLE_ROWS} most recent rows."
                )
            csv_text = _rows_to_csv(columns, flat_rows)
            sections.append(
                TabularSection(text=csv_text, link=summary.get("experiment_url") or "")
            )
            file_id = self._stage_csv(csv_text)
        sections.insert(
            0,
            TextSection(text="\n".join(lines), link=summary.get("experiment_url")),
        )

        return Document(
            id=f"braintrust:exp:{ref.id}",
            source=DocumentSource.BRAINTRUST,
            title=f"Braintrust experiment: {ref.name}",
            semantic_identifier=f"Experiment: {ref.name}",
            sections=sections,
            metadata=_coerce_metadata(
                {
                    "object_type": "experiment",
                    "project": ref.project_name,
                    "experiment": ref.name,
                    "baseline_experiment": summary.get("comparison_experiment_name"),
                }
            ),
            doc_updated_at=_parse_time(ref.created),
            file_id=file_id,
        )

    def _seed_phase(
        self,
        checkpoint: BraintrustCheckpoint,
        start_dt: datetime,
        end_dt: datetime,
    ) -> CheckpointOutput[BraintrustCheckpoint]:
        if checkpoint.phase == BraintrustPhase.PROMPTS:
            refs = self._to_refs(self._list_objects("prompt"))
        elif checkpoint.phase == BraintrustPhase.DATASETS:
            refs = []
            for ref in self._to_refs(self._list_objects("dataset")):
                try:
                    if self._has_rows_in_window("dataset", ref.id, start_dt, end_dt):
                        refs.append(ref)
                except Exception as e:
                    yield ConnectorFailure(
                        failed_entity=EntityFailure(entity_id=ref.id),
                        failure_message=f"Failed to probe Braintrust dataset '{ref.id}': {e}",
                        exception=e,
                    )
        else:
            # Experiments are write-once per run: only ones created in the
            # window need (re-)indexing; older docs stay as indexed.
            refs = [
                ref
                for ref in self._to_refs(self._list_objects("experiment"))
                if (created := _parse_time(ref.created)) is None
                or start_dt <= created <= end_dt
            ]
        checkpoint.todo = refs
        return checkpoint

    def _advance_phase(self, checkpoint: BraintrustCheckpoint) -> BraintrustCheckpoint:
        checkpoint.phase = _PHASE_ORDER[_PHASE_ORDER.index(checkpoint.phase) + 1]
        checkpoint.todo = None
        if checkpoint.phase == BraintrustPhase.DONE:
            checkpoint.has_more = False
        return checkpoint

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: BraintrustCheckpoint,
    ) -> CheckpointOutput[BraintrustCheckpoint]:
        checkpoint = copy.deepcopy(checkpoint)
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)

        if checkpoint.phase == BraintrustPhase.DONE:
            checkpoint.has_more = False
            return checkpoint

        if checkpoint.todo is None:
            return (yield from self._seed_phase(checkpoint, start_dt, end_dt))

        if not checkpoint.todo:
            return self._advance_phase(checkpoint)

        if checkpoint.phase == BraintrustPhase.PROMPTS:
            batch = checkpoint.todo[-_PROMPTS_PER_CALL:]
            del checkpoint.todo[-_PROMPTS_PER_CALL:]
            for ref in batch:
                try:
                    prompt = self._get(f"/v1/prompt/{ref.id}")
                    yield self._prompt_to_document(prompt, ref.project_name or "")
                except Exception as e:
                    yield ConnectorFailure(
                        failed_entity=EntityFailure(entity_id=ref.id),
                        failure_message=f"Failed to fetch Braintrust prompt: {e}",
                        exception=e,
                    )
        elif checkpoint.phase == BraintrustPhase.DATASETS:
            ref = checkpoint.todo.pop()
            try:
                rows = self._btql_rows("dataset", ref.id)
                yield self._dataset_to_document(ref, rows)
            except Exception as e:
                yield ConnectorFailure(
                    failed_entity=EntityFailure(entity_id=ref.id),
                    failure_message=f"Failed to build Braintrust dataset table '{ref.id}': {e}",
                    exception=e,
                )
        else:
            batch = checkpoint.todo[-_SUMMARIES_PER_CALL:]
            del checkpoint.todo[-_SUMMARIES_PER_CALL:]
            lookback = self._experiment_row_lookback_days
            cutoff = (
                datetime.now(tz=timezone.utc) - timedelta(days=lookback)
                if lookback > 0
                else None
            )
            for ref in batch:
                created = _parse_time(ref.created)
                include_table = cutoff is None or created is None or created >= cutoff
                try:
                    yield self._experiment_to_document(ref, include_table)
                except Exception as e:
                    yield ConnectorFailure(
                        failed_entity=EntityFailure(entity_id=ref.id),
                        failure_message=f"Failed to build Braintrust experiment doc '{ref.id}': {e}",
                        exception=e,
                    )

        return checkpoint

    def build_dummy_checkpoint(self) -> BraintrustCheckpoint:
        return BraintrustCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> BraintrustCheckpoint:
        return BraintrustCheckpoint.model_validate_json(checkpoint_json)

    def validate_connector_settings(self) -> None:
        try:
            data = self._get("/v1/project", params={"limit": 1})
        except CredentialInvalidError:
            raise
        except requests.HTTPError as e:
            raise ConnectorValidationError(
                f"Failed to reach the Braintrust API: {e}"
            ) from e
        if self._project_name:
            projects = self._list_objects("project")
            if not any(p.get("name") == self._project_name for p in projects):
                raise ConnectorValidationError(
                    f"Braintrust project '{self._project_name}' was not found"
                )
        elif not isinstance(data.get("objects"), list):
            raise ConnectorValidationError(
                "Unexpected response shape from the Braintrust API"
            )
