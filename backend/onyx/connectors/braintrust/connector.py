import copy
import json
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from enum import Enum
from typing import Any

import requests
from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE
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
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

_BASE_URL = "https://api.braintrust.dev"
_API_KEY = "braintrust_api_key"
_TIMEOUT = 60
_NUM_RETRIES = 5
_MAX_CALLS_PER_SECOND = 4
_LIST_PAGE_SIZE = 100
_EVENT_PAGE_SIZE = 200
_SUMMARIES_PER_CALL = 10
_PROMPTS_PER_CALL = 50
# Nightly eval runs re-create every row under a new experiment, so unbounded
# per-row indexing grows with time, not suite size. 0 disables the cutoff.
_DEFAULT_EXPERIMENT_ROW_LOOKBACK_DAYS = 30


class _TransientServerError(Exception):
    pass


class BraintrustPhase(str, Enum):
    PROMPTS = "prompts"
    DATASET_ROWS = "dataset_rows"
    EXPERIMENT_SUMMARIES = "experiment_summaries"
    EXPERIMENT_ROWS = "experiment_rows"
    DONE = "done"


_PHASE_ORDER = [
    BraintrustPhase.PROMPTS,
    BraintrustPhase.DATASET_ROWS,
    BraintrustPhase.EXPERIMENT_SUMMARIES,
    BraintrustPhase.EXPERIMENT_ROWS,
    BraintrustPhase.DONE,
]


class BraintrustObjectRef(BaseModel):
    id: str
    name: str
    project_id: str | None = None
    project_name: str | None = None
    base_exp_id: str | None = None
    dataset_id: str | None = None
    created: str | None = None


class BraintrustCheckpoint(ConnectorCheckpoint):
    phase: BraintrustPhase = BraintrustPhase.PROMPTS
    todo: list[BraintrustObjectRef] | None = None
    cursor: str | None = None


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


class BraintrustConnector(CheckpointedConnector[BraintrustCheckpoint]):
    def __init__(
        self,
        project_name: str | None = None,
        experiment_row_lookback_days: int = _DEFAULT_EXPERIMENT_ROW_LOOKBACK_DAYS,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self._project_name = project_name
        self._experiment_row_lookback_days = experiment_row_lookback_days
        self._batch_size = batch_size
        self._api_key: str | None = None
        self._rate_limited_get: Callable[..., requests.Response] | None = None

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
    def _raw_get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> requests.Response:
        response = requests.get(
            f"{_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            params={k: v for k, v in (params or {}).items() if v is not None},
            timeout=_TIMEOUT,
        )
        if response.status_code in (500, 502, 503, 504):
            raise _TransientServerError(
                f"Braintrust API returned {response.status_code} for {path}"
            )
        return response

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._api_key:
            raise ConnectorMissingCredentialError("Braintrust")
        if self._rate_limited_get is None:
            self._rate_limited_get = wrap_request_to_handle_ratelimiting(self._raw_get)
        response = self._rate_limited_get(path, params)
        if response.status_code in (401, 403):
            raise CredentialInvalidError(
                f"Braintrust API rejected the API key ({response.status_code})"
            )
        response.raise_for_status()
        return response.json()

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

    def _fetch_events_page(
        self, object_path: str, object_id: str, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        data = self._get(
            f"/v1/{object_path}/{object_id}/fetch",
            params={"limit": _EVENT_PAGE_SIZE, "cursor": cursor},
        )
        return data.get("events", []), data.get("cursor")

    def _project_names_by_id(self) -> dict[str, str]:
        return {
            project["id"]: project.get("name", "")
            for project in self._list_objects("project")
        }

    def _to_refs(
        self, objects: list[dict[str, Any]], project_names: dict[str, str]
    ) -> list[BraintrustObjectRef]:
        refs = []
        for obj in objects:
            project_id = obj.get("project_id")
            refs.append(
                BraintrustObjectRef(
                    id=obj["id"],
                    name=obj.get("name", obj["id"]),
                    project_id=project_id,
                    project_name=project_names.get(project_id or "", None),
                    base_exp_id=obj.get("base_exp_id"),
                    dataset_id=obj.get("dataset_id"),
                    created=obj.get("created"),
                )
            )
        return refs

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

    def _event_to_document(
        self,
        event: dict[str, Any],
        parent: BraintrustObjectRef,
        object_type: str,
    ) -> Document:
        scores = event.get("scores") or {}
        lines = []
        if object_type == "dataset_row":
            lines.append(f"Dataset row from dataset '{parent.name}'.")
        else:
            lines.append(f"Experiment result row from experiment '{parent.name}'.")
        for label, key in (
            ("Input", "input"),
            ("Output", "output"),
            ("Expected", "expected"),
        ):
            rendered = _render_value(event.get(key))
            if rendered:
                lines.append(f"{label}: {rendered}")
        if scores:
            score_text = ", ".join(f"{name}={value}" for name, value in scores.items())
            lines.append(f"Scores: {score_text}")
        if event.get("metadata"):
            lines.append(f"Metadata: {_render_value(event['metadata'])}")

        id_prefix = "ds" if object_type == "dataset_row" else "exp"
        return Document(
            id=f"braintrust:{id_prefix}:{parent.id}:row:{event['id']}",
            source=DocumentSource.BRAINTRUST,
            title=f"Braintrust {parent.name} row",
            semantic_identifier=f"{parent.name} / row {event['id'][:8]}",
            sections=[TextSection(text="\n".join(lines))],
            metadata=_coerce_metadata(
                {
                    "object_type": object_type,
                    "project": parent.project_name,
                    "dataset"
                    if object_type == "dataset_row"
                    else "experiment": parent.name,
                    "scores": {k: str(v) for k, v in scores.items()}
                    if scores
                    else None,
                }
            ),
            doc_updated_at=_parse_time(event.get("created")),
        )

    def _experiment_summary_document(self, experiment: BraintrustObjectRef) -> Document:
        params: dict[str, Any] = {"summarize_scores": True}
        if experiment.base_exp_id:
            params["comparison_experiment_id"] = experiment.base_exp_id
        summary = self._get(f"/v1/experiment/{experiment.id}/summarize", params=params)

        lines = [
            f"Experiment '{experiment.name}' in project {experiment.project_name}."
        ]
        comparison_name = summary.get("comparison_experiment_name")

        scores = summary.get("scores") or {}
        score_parts = []
        delta_parts = []
        for score_name, score_info in scores.items():
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
            baseline = comparison_name or "baseline"
            lines.append(f"Versus {baseline}: {', '.join(delta_parts)}.")

        metrics = summary.get("metrics") or {}
        metric_parts = []
        for metric_name, metric_info in metrics.items():
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

        return Document(
            id=f"braintrust:exp:{experiment.id}",
            source=DocumentSource.BRAINTRUST,
            title=f"Braintrust experiment: {experiment.name}",
            semantic_identifier=f"Experiment: {experiment.name}",
            sections=[
                TextSection(
                    text="\n".join(lines),
                    link=summary.get("experiment_url"),
                )
            ],
            metadata=_coerce_metadata(
                {
                    "object_type": "experiment_summary",
                    "project": experiment.project_name,
                    "experiment": experiment.name,
                    "baseline_experiment": comparison_name,
                }
            ),
            doc_updated_at=_parse_time(experiment.created),
        )

    def _seed_phase(self, checkpoint: BraintrustCheckpoint) -> BraintrustCheckpoint:
        project_names = self._project_names_by_id()
        if checkpoint.phase == BraintrustPhase.PROMPTS:
            objects = self._list_objects("prompt")
        elif checkpoint.phase == BraintrustPhase.DATASET_ROWS:
            objects = self._list_objects("dataset")
        else:
            objects = self._list_objects("experiment")
        refs = self._to_refs(objects, project_names)
        if (
            checkpoint.phase == BraintrustPhase.EXPERIMENT_ROWS
            and self._experiment_row_lookback_days > 0
        ):
            cutoff = datetime.now(tz=timezone.utc) - timedelta(
                days=self._experiment_row_lookback_days
            )
            refs = [
                ref
                for ref in refs
                if (created := _parse_time(ref.created)) is None or created >= cutoff
            ]
        checkpoint.todo = refs
        checkpoint.cursor = None
        return checkpoint

    def _advance_phase(self, checkpoint: BraintrustCheckpoint) -> BraintrustCheckpoint:
        next_index = _PHASE_ORDER.index(checkpoint.phase) + 1
        checkpoint.phase = _PHASE_ORDER[next_index]
        checkpoint.todo = None
        checkpoint.cursor = None
        if checkpoint.phase == BraintrustPhase.DONE:
            checkpoint.has_more = False
        return checkpoint

    def _yield_event_docs(
        self,
        checkpoint: BraintrustCheckpoint,
        object_path: str,
        object_type: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> Iterator[Document | ConnectorFailure]:
        assert checkpoint.todo is not None
        parent = checkpoint.todo[-1]
        events, next_cursor = self._fetch_events_page(
            object_path, parent.id, checkpoint.cursor
        )
        for event in events:
            created = _parse_time(event.get("created"))
            if created and not (start_dt <= created <= end_dt):
                continue
            try:
                yield self._event_to_document(event, parent, object_type)
            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=f"braintrust:{object_path}:{parent.id}:row:{event.get('id', 'unknown')}",
                    ),
                    failure_message=f"Failed to map Braintrust event: {e}",
                    exception=e,
                )
        if next_cursor and events:
            checkpoint.cursor = next_cursor
        else:
            checkpoint.todo.pop()
            checkpoint.cursor = None

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
            return self._seed_phase(checkpoint)

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
                        failed_document=DocumentFailure(
                            document_id=f"braintrust:prompt:{ref.id}",
                        ),
                        failure_message=f"Failed to fetch Braintrust prompt: {e}",
                        exception=e,
                    )
        elif checkpoint.phase == BraintrustPhase.DATASET_ROWS:
            yield from self._yield_event_docs(
                checkpoint, "dataset", "dataset_row", start_dt, end_dt
            )
        elif checkpoint.phase == BraintrustPhase.EXPERIMENT_SUMMARIES:
            batch = checkpoint.todo[-_SUMMARIES_PER_CALL:]
            del checkpoint.todo[-_SUMMARIES_PER_CALL:]
            for ref in batch:
                try:
                    yield self._experiment_summary_document(ref)
                except Exception as e:
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=f"braintrust:exp:{ref.id}",
                        ),
                        failure_message=f"Failed to summarize Braintrust experiment: {e}",
                        exception=e,
                    )
        elif checkpoint.phase == BraintrustPhase.EXPERIMENT_ROWS:
            yield from self._yield_event_docs(
                checkpoint, "experiment", "experiment_row", start_dt, end_dt
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


if __name__ == "__main__":
    import os
    import time

    connector = BraintrustConnector(project_name=os.environ.get("BRAINTRUST_PROJECT"))
    connector.load_credentials({_API_KEY: os.environ["BRAINTRUST_API_KEY"]})
    connector.validate_connector_settings()

    from tests.daily.connectors.utils import load_all_from_connector

    for doc in load_all_from_connector(
        connector=connector, start=0, end=time.time()
    ).documents:
        print(doc.to_short_descriptor())
