"""Headless execution of one flow run.

The Celery task is a thin wrapper around ``run_flow_logic`` here, so the
interesting half can be imported and driven directly from a test without a
worker.

The recorder deliberately opens a short session per write instead of holding
one open for the whole run. A run spends most of its life waiting on somebody
else's API, and pinning a pooled connection through that is how a handful of
slow flows starve everything else.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    FlowErrorClass,
    FlowNodeKind,
    FlowNodeRunStatus,
    FlowRunStatus,
)
from onyx.db.flow import (
    ensure_webhook_signing_secret,
    finish_node_run,
    get_node_run,
    get_run,
    mark_run_status,
    record_node_waiting,
    record_skipped_node,
    start_node_run,
)
from onyx.flows.engine import RecordedNode, RunResult, execute_flow
from onyx.flows.models import SpecError, parse_spec
from onyx.flows.nodes import NodeRuntime, build_http_client
from onyx.llm.factory import get_default_llm
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Ceiling for one run, enforced in the engine. Celery's thread-pool worker
# ignores soft_time_limit without saying so, so this is the only limit there is.
RUN_BUDGET_SECONDS = 15 * 60

# A node with a longer timeout than this is rejected by the spec anyway; the
# client-level timeout is just a backstop for a connection that never settles.
HTTP_CLIENT_TIMEOUT_SECONDS = 120.0


@dataclass
class DatabaseRecorder:
    """Writes node history for one run, one short transaction at a time."""

    run_id: UUID

    def begin_node(
        self,
        *,
        node_id: str,
        kind: FlowNodeKind,
        item_index: int,
        node_input: dict[str, Any] | None,
    ) -> RecordedNode | None:
        with get_session_with_current_tenant() as db_session:
            node_run, existed = start_node_run(
                db_session=db_session,
                run_id=self.run_id,
                node_id=node_id,
                kind=kind,
                item_index=item_index,
                node_input=node_input,
            )
            status = node_run.status
            stored = node_run.output
            db_session.commit()

        if not existed:
            return None
        # `output` is boxed on write so the column keeps one shape.
        return RecordedNode(
            status=status, output=None if stored is None else stored.get("value")
        )

    def finish_node(
        self,
        *,
        node_id: str,
        item_index: int,
        status: FlowNodeRunStatus,
        output: Any,
        attempt: int,
    ) -> None:
        self._close_node(
            node_id=node_id,
            item_index=item_index,
            status=status,
            output=output,
            attempt=attempt,
        )

    def fail_node(
        self,
        *,
        node_id: str,
        item_index: int,
        error_class: FlowErrorClass,
        error_detail: str,
        attempt: int,
    ) -> None:
        self._close_node(
            node_id=node_id,
            item_index=item_index,
            status=FlowNodeRunStatus.FAILED,
            attempt=attempt,
            error_class=error_class,
            error_detail=error_detail,
        )

    def _close_node(
        self,
        *,
        node_id: str,
        item_index: int,
        status: FlowNodeRunStatus,
        attempt: int,
        output: Any = None,
        error_class: FlowErrorClass | None = None,
        error_detail: str | None = None,
    ) -> None:
        """Write the terminal state onto the row ``begin_node`` opened.

        The row is always there — the engine calls ``begin_node`` first — so a
        miss means something has gone wrong enough that inventing a row would
        only hide it.
        """
        with get_session_with_current_tenant() as db_session:
            node_run = get_node_run(
                db_session=db_session,
                run_id=self.run_id,
                node_id=node_id,
                item_index=item_index,
            )
            if node_run is None:
                logger.error(
                    "no node row to close run_id=%s node=%s item=%d",
                    self.run_id,
                    node_id,
                    item_index,
                )
                return
            finish_node_run(
                db_session=db_session,
                node_run=node_run,
                status=status,
                output=output,
                attempt=attempt,
                error_class=error_class,
                error_detail=error_detail,
            )
            db_session.commit()

    def park_node(
        self, *, node_id: str, item_index: int, detail: dict[str, Any]
    ) -> None:
        with get_session_with_current_tenant() as db_session:
            parked = record_node_waiting(
                db_session=db_session,
                run_id=self.run_id,
                node_id=node_id,
                item_index=item_index,
                detail=detail,
            )
            if parked is None:
                logger.error(
                    "no node row to park run_id=%s node=%s", self.run_id, node_id
                )
            db_session.commit()

    def skip_node(self, *, node_id: str, kind: FlowNodeKind) -> None:
        with get_session_with_current_tenant() as db_session:
            record_skipped_node(
                db_session=db_session, run_id=self.run_id, node_id=node_id, kind=kind
            )
            db_session.commit()


def run_flow_logic(run_id: UUID) -> None:
    """Drive one queued run as far as it can go.

    Usually that is a terminal status. A flow with an approval step instead
    ends up AWAITING_DECISION, and the same function runs it again — from the
    top, reusing the recorded rows — once somebody answers.

    Never raises for a flow-level problem: the run row is the report, and a
    raised exception would only tell Celery to try the whole thing again.
    """
    started = time.monotonic()

    with get_session_with_current_tenant() as db_session:
        run = get_run(db_session=db_session, run_id=run_id)
        if run is None:
            logger.warning("flow run vanished before execution run_id=%s", run_id)
            return
        if run.status != FlowRunStatus.QUEUED:
            # Celery redelivery, or a sweeper already gave up on this row.
            logger.info(
                "flow run is not queued, nothing to do run_id=%s status=%s",
                run_id,
                run.status,
            )
            return

        flow = run.flow
        raw_spec = run.version.spec if run.version is not None else flow.draft_spec
        trigger_payload = run.trigger_payload
        flow_id = flow.id
        # Read here rather than in the node: the executor has no session, and
        # a run should not be opening one halfway through a delivery.
        signing_secret = ensure_webhook_signing_secret(db_session=db_session, flow=flow)

        try:
            spec = parse_spec(raw_spec)
        except SpecError as exc:
            logger.error("flow run has an unusable spec run_id=%s: %s", run_id, exc)
            mark_run_status(
                db_session=db_session,
                run=run,
                status=FlowRunStatus.FAILED,
                error_class=FlowErrorClass.INVALID_SPEC,
                error_detail=str(exc),
            )
            db_session.commit()
            return

        mark_run_status(db_session=db_session, run=run, status=FlowRunStatus.RUNNING)
        db_session.commit()

    logger.info(
        "flow run starting run_id=%s flow_id=%s nodes=%d",
        run_id,
        flow_id,
        len(spec.nodes),
    )

    result = _execute(
        spec=spec,
        run_id=run_id,
        trigger_payload=trigger_payload,
        signing_secret=signing_secret,
    )

    with get_session_with_current_tenant() as db_session:
        run = get_run(db_session=db_session, run_id=run_id)
        if run is None:
            logger.warning("flow run vanished mid-execution run_id=%s", run_id)
            return
        mark_run_status(
            db_session=db_session,
            run=run,
            status=result.status,
            error_class=result.error_class,
            error_detail=_failure_detail(result),
        )
        db_session.commit()

    logger.info(
        "flow run %s run_id=%s status=%s seconds=%.1f",
        "parked" if result.status == FlowRunStatus.AWAITING_DECISION else "finished",
        run_id,
        result.status.value,
        time.monotonic() - started,
    )


def _execute(
    *,
    spec: Any,
    run_id: UUID,
    trigger_payload: Any,
    signing_secret: str | None = None,
) -> RunResult:
    """Run the graph, converting an unexpected crash into a FAILED result."""
    runtime = NodeRuntime(
        http_client=build_http_client(HTTP_CLIENT_TIMEOUT_SECONDS),
        llm_provider=_default_llm_provider,
        webhook_signing_secret=signing_secret,
    )
    try:
        return execute_flow(
            spec=spec,
            runtime=runtime,
            recorder=DatabaseRecorder(run_id=run_id),
            trigger_payload=trigger_payload,
            budget_seconds=RUN_BUDGET_SECONDS,
        )
    except Exception as exc:
        logger.exception("flow run crashed run_id=%s", run_id)
        return RunResult(
            status=FlowRunStatus.FAILED,
            outputs={},
            error_class=FlowErrorClass.NODE_EXCEPTION,
            error_detail=f"{type(exc).__name__}: {exc}",
        )
    finally:
        runtime.close()


def _default_llm_provider() -> LLM:
    return get_default_llm()


def _failure_detail(result: RunResult) -> str | None:
    """Put the failing node in front of the message.

    The run list shows this string and nothing else, so it has to answer
    "where did it break" before "what did it say".
    """
    if result.error_detail is None:
        return None
    if result.failed_node_id:
        return f"[{result.failed_node_id}] {result.error_detail}"
    return result.error_detail
