"""Request and response shapes for the flows API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from onyx.db.enums import (
    FlowNodeKind,
    FlowNodeRunStatus,
    FlowRunStatus,
    FlowStatus,
    FlowTriggerKind,
    FlowTriggerSource,
)
from onyx.db.models import Flow, FlowNodeRun, FlowRun, FlowTrigger

MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000


class TriggerDefinition(BaseModel):
    """A trigger as the editor submits it."""

    model_config = ConfigDict(extra="forbid")

    kind: FlowTriggerKind
    # SCHEDULE expects {"cron": "0 9 * * 1-5"}.
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class TriggerView(BaseModel):
    id: UUID
    kind: FlowTriggerKind
    config: dict[str, Any]
    enabled: bool
    next_run_at: datetime | None
    # Present only on the response that mints it, so a secret is never served
    # twice. Rotating means replacing the trigger.
    webhook_secret: str | None = None

    @classmethod
    def from_model(
        cls, trigger: FlowTrigger, *, reveal_secret: bool = False
    ) -> TriggerView:
        secret: str | None = None
        if reveal_secret and trigger.webhook_secret is not None:
            secret = trigger.webhook_secret.get_value(apply_mask=False)
        return cls(
            id=trigger.id,
            kind=trigger.kind,
            config=trigger.config or {},
            enabled=trigger.enabled,
            next_run_at=trigger.next_run_at,
            webhook_secret=secret,
        )


class CreateFlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    spec: dict[str, Any]


class UpdateFlowRequest(BaseModel):
    """A partial edit. Omitted fields are left alone."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    spec: dict[str, Any] | None = None


class SetStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FlowStatus


class ReplaceTriggersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    triggers: list[TriggerDefinition] = Field(default_factory=list, max_length=10)


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Becomes `{{ trigger.* }}`, so a manual run can stand in for a webhook.
    payload: dict[str, Any] | None = None


class FlowSummary(BaseModel):
    """Row in the flow list."""

    id: UUID
    name: str
    description: str | None
    status: FlowStatus
    published_version: int | None
    node_count: int
    triggers: list[TriggerView]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, flow: Flow) -> FlowSummary:
        return cls(
            id=flow.id,
            name=flow.name,
            description=flow.description,
            status=flow.status,
            published_version=flow.published_version,
            node_count=len((flow.draft_spec or {}).get("nodes", [])),
            triggers=[TriggerView.from_model(trigger) for trigger in flow.triggers],
            created_at=flow.created_at,
            updated_at=flow.updated_at,
        )


class FlowDetail(FlowSummary):
    """The list row plus the spec the editor renders."""

    spec: dict[str, Any]
    has_unpublished_changes: bool

    @classmethod
    def build(cls, flow: Flow, *, published_spec: dict[str, Any] | None) -> FlowDetail:
        summary = FlowSummary.from_model(flow)
        return cls(
            **summary.model_dump(),
            spec=flow.draft_spec,
            has_unpublished_changes=(
                published_spec is None or published_spec != flow.draft_spec
            ),
        )


class NodeRunView(BaseModel):
    node_id: str
    kind: FlowNodeKind
    status: FlowNodeRunStatus
    item_index: int
    attempt: int
    input: dict[str, Any] | None
    output: Any
    error_class: str | None
    error_detail: str | None
    started_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_model(cls, node_run: FlowNodeRun) -> NodeRunView:
        stored = node_run.output
        return cls(
            node_id=node_run.node_id,
            kind=node_run.kind,
            status=node_run.status,
            item_index=node_run.item_index,
            attempt=node_run.attempt,
            input=node_run.input,
            # Unboxed here so the canvas sees what the node actually produced.
            output=None if stored is None else stored.get("value"),
            error_class=node_run.error_class,
            error_detail=node_run.error_detail,
            started_at=node_run.started_at,
            finished_at=node_run.finished_at,
        )


class RunSummary(BaseModel):
    id: UUID
    flow_id: UUID
    status: FlowRunStatus
    trigger_source: FlowTriggerSource
    skip_reason: str | None
    error_class: str | None
    error_detail: str | None
    started_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_model(cls, run: FlowRun) -> RunSummary:
        return cls(
            id=run.id,
            flow_id=run.flow_id,
            status=run.status,
            trigger_source=run.trigger_source,
            skip_reason=run.skip_reason,
            error_class=run.error_class,
            error_detail=run.error_detail,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )


class RunDetail(RunSummary):
    """A run plus every node execution, for the run inspector."""

    trigger_payload: dict[str, Any] | None
    node_runs: list[NodeRunView]

    @classmethod
    def from_model(cls, run: FlowRun) -> RunDetail:
        summary = RunSummary.from_model(run)
        return cls(
            **summary.model_dump(),
            trigger_payload=run.trigger_payload,
            node_runs=[NodeRunView.from_model(node) for node in run.node_runs],
        )


class WebhookAccepted(BaseModel):
    run_id: UUID
