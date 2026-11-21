"""Scheduled runs on the chat engine: the run follows its chat response, a
fire replaces a run that waits for approval, and the task's integrations
apply only while the run is in flight."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import PropertyMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.agents.models import RunFailure, RunFailureKind, RunStatus
from onyx.background.celery.tasks.scheduled_tasks.tasks import (
    NO_RESPONSE_OLDER_THAN,
    RUN_EXPIRES_SECONDS,
    _cancel_parked_runs,
    _sync_chat_runs,
    cleanup_stuck_scheduled_runs,
    dispatch_due_scheduled_tasks,
)
from onyx.cache.factory import get_cache_backend
from onyx.chat.run_store import _owner_key
from onyx.configs.constants import (
    DEFAULT_PERSONA_ID,
    MessageType,
    NotificationType,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.db.chat import (
    create_chat_session,
    delete_chat_session,
    get_chat_sessions_by_user,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    IntegrationActionPolicyValue,
    PluginInstallationPolicy,
    ScheduledTaskErrorClass,
    ScheduledTaskRunStatus,
    ScheduledTaskSkipReason,
    ScheduledTaskStatus,
    ScheduledTaskTriggerSource,
)
from onyx.db.models import (
    ChatMessage,
    IntegrationActionPolicy,
    Notification,
    ScheduledTask,
    ScheduledTaskRun,
    User,
)
from onyx.db.scheduled_task import (
    create_scheduled_task,
    find_stuck_runs,
    insert_run,
    mark_run_status,
    requeue_queued_run__no_commit,
    sync_chat_run__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.models import ActionSettings, EffectivePolicy
from onyx.integrations.policy import chat_integrations, resolve_chat_action_policy
from onyx.scheduled_tasks.executor import _start_run, run_scheduled_task_logic
from onyx.tools.models import IntegrationLinkConfiguration
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
)


@pytest.fixture
def owner(
    make_test_user: MakeTestUser,
    tenant_context: None,  # noqa: ARG001
) -> User:
    return make_test_user("scheduled_chat_owner")


@pytest.fixture
def cleanup(db_session: Session, owner: User) -> Generator[list[int], None, None]:
    integration_ids: list[int] = []
    try:
        yield integration_ids
    finally:
        db_session.rollback()
        db_session.execute(
            delete(ScheduledTask).where(ScheduledTask.user_id == owner.id)
        )
        db_session.execute(delete(Notification).where(Notification.user_id == owner.id))
        db_session.commit()
        delete_integrations(db_session, integration_ids)


def _task(
    db_session: Session,
    owner: User,
    *,
    due: bool = False,
    integrations: list[IntegrationLinkConfiguration] | None = None,
) -> ScheduledTask:
    task = create_scheduled_task(
        db_session=db_session,
        user_id=owner.id,
        name="Daily digest",
        prompt="Summarize my day",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        integrations=integrations,
    )
    if due:
        task.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    db_session.commit()
    return task


def _run_with_response(
    db_session: Session,
    task: ScheduledTask,
    response_status: RunStatus,
    *,
    message: str = "",
    failure: RunFailure | None = None,
) -> tuple[ScheduledTaskRun, ChatMessage]:
    """A RUNNING run whose chat has the task prompt and one response."""
    chat = create_chat_session(
        db_session,
        description=task.name,
        user_id=task.user_id,
        persona_id=DEFAULT_PERSONA_ID,
    )
    prompt = ChatMessage(
        chat_session_id=chat.id,
        message=task.prompt,
        token_count=3,
        message_type=MessageType.USER,
    )
    db_session.add(prompt)
    db_session.flush()
    response = ChatMessage(
        chat_session_id=chat.id,
        parent_message_id=prompt.id,
        message=message,
        token_count=3,
        message_type=MessageType.ASSISTANT,
        response_status=response_status,
        response_failure=failure,
    )
    db_session.add(response)
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
    )
    mark_run_status(
        db_session=db_session,
        run_id=run.id,
        status=ScheduledTaskRunStatus.RUNNING,
        chat_session_id=chat.id,
    )
    db_session.commit()
    return run, response


def _notifications(db_session: Session, owner: User) -> list[NotificationType]:
    return [notif_type for notif_type, _ in _notification_links(db_session, owner)]


def _notification_links(
    db_session: Session, owner: User
) -> list[tuple[NotificationType, str]]:
    return [
        (notification.notif_type, (notification.additional_data or {})["link"])
        for notification in db_session.scalars(
            select(Notification).where(Notification.user_id == owner.id)
        )
    ]


@pytest.mark.parametrize(
    ("response_status", "run_status", "version", "notification"),
    [
        (RunStatus.RUNNING, ScheduledTaskRunStatus.RUNNING, 0, None),
        (
            RunStatus.SUSPENDED,
            ScheduledTaskRunStatus.AWAITING_APPROVAL,
            1,
            NotificationType.SCHEDULED_TASK_AWAITING_APPROVAL,
        ),
        (RunStatus.COMPLETE, ScheduledTaskRunStatus.SUCCEEDED, 1, None),
        (RunStatus.LIMIT, ScheduledTaskRunStatus.SUCCEEDED, 1, None),
        (RunStatus.CANCELLED, ScheduledTaskRunStatus.CANCELLED, 1, None),
        (
            RunStatus.ERROR,
            ScheduledTaskRunStatus.FAILED,
            1,
            NotificationType.SCHEDULED_TASK_FAILED,
        ),
    ],
)
def test_a_run_takes_the_status_of_its_chat_response(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
    response_status: RunStatus,
    run_status: ScheduledTaskRunStatus,
    version: int,
    notification: NotificationType | None,
) -> None:
    run, _ = _run_with_response(
        db_session,
        _task(db_session, owner),
        response_status,
        message="Three meetings and one launch.",
        failure=RunFailure(kind=RunFailureKind.EXECUTION, message="model down"),
    )

    sync_chat_run__no_commit(db_session, run)
    sync_chat_run__no_commit(db_session, run)
    db_session.commit()

    db_session.refresh(run)
    assert run.status == run_status
    assert run.version == version
    assert _notification_links(db_session, owner) == (
        [(notification, f"/app?chatId={run.chat_session_id}")] if notification else []
    )
    if run_status == ScheduledTaskRunStatus.SUCCEEDED:
        assert run.summary == "Three meetings and one launch."
    if run_status == ScheduledTaskRunStatus.FAILED:
        assert run.error_detail == "model down"


def _dispatch_with_fake_broker() -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    class _FakeApp:
        def send_task(self, name: str, **kwargs: Any) -> None:
            sent.append({"name": name, **kwargs})

    task_instance = dispatch_due_scheduled_tasks.run.__self__
    with patch.object(
        type(task_instance), "app", new_callable=PropertyMock, return_value=_FakeApp()
    ):
        dispatch_due_scheduled_tasks.run(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE  # ty: ignore[invalid-argument-type]
        )
    return sent


def test_the_next_fire_cancels_a_run_that_waits_for_approval(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner, due=True)
    parked, response = _run_with_response(db_session, task, RunStatus.SUSPENDED)

    sent = _dispatch_with_fake_broker()

    db_session.expire_all()
    runs = {
        run.id: run
        for run in db_session.scalars(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task.id)
        )
    }
    assert runs[parked.id].status == ScheduledTaskRunStatus.CANCELLED
    assert runs[parked.id].error_class == "superseded_by_next_fire"
    [new_run] = [run for run_id, run in runs.items() if run_id != parked.id]
    assert new_run.status == ScheduledTaskRunStatus.QUEUED
    assert [UUID(message["kwargs"]["run_id"]) for message in sent] == [new_run.id]
    db_session.refresh(response)
    assert response.response_status == RunStatus.CANCELLED


def test_a_run_that_waits_a_day_for_approval_is_cancelled(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner)
    fresh, _ = _run_with_response(db_session, task, RunStatus.SUSPENDED)
    stale, response = _run_with_response(db_session, task, RunStatus.SUSPENDED)
    for run in (fresh, stale):
        sync_chat_run__no_commit(db_session, run)
    stale.started_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db_session.commit()

    cleanup_stuck_scheduled_runs.run(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE  # ty: ignore[invalid-argument-type]
    )

    db_session.expire_all()
    assert fresh.status == ScheduledTaskRunStatus.AWAITING_APPROVAL
    assert stale.status == ScheduledTaskRunStatus.CANCELLED
    assert stale.error_class == "approval_timeout"
    assert response.response_status == RunStatus.CANCELLED


def test_a_chat_uses_the_task_integrations_only_while_its_run_is_in_flight(
    db_session: Session,
    owner: User,
    cleanup: list[int],
) -> None:
    linked, _ = make_mcp_integration(
        db_session,
        server_url=f"https://linked-{uuid4().hex[:8]}.example.com/mcp",
        name=f"linked-{uuid4().hex[:8]}",
        tools=("send_report",),
    )
    other, _ = make_mcp_integration(
        db_session,
        server_url=f"https://other-{uuid4().hex[:8]}.example.com/mcp",
        name=f"other-{uuid4().hex[:8]}",
        tools=("search",),
    )
    cleanup += [linked.id, other.id]
    give_access(
        db_session,
        [linked, other],
        installation_policy=PluginInstallationPolicy.REQUIRED,
    )
    task_settings = ActionSettings(actions={"send_report": "allow"})
    task = _task(
        db_session,
        owner,
        integrations=[
            IntegrationLinkConfiguration(
                integration_id=linked.id, action_settings=task_settings
            )
        ],
    )
    run, response = _run_with_response(db_session, task, RunStatus.RUNNING)
    assert run.chat_session_id is not None

    def used() -> dict[int, ActionSettings]:
        return {
            integration_id: held.settings
            for integration_id, held in chat_integrations(
                db_session, owner.id, DEFAULT_PERSONA_ID, {}, run.chat_session_id
            ).items()
            if integration_id in (linked.id, other.id)
        }

    assert used() == {linked.id: task_settings}

    # An approval resumed the response and it ended; the run status follows
    # only at the next dispatch tick.
    response.response_status = RunStatus.COMPLETE
    db_session.commit()

    assert used() == {linked.id: ActionSettings(), other.id: ActionSettings()}


def test_scheduled_chats_stay_out_of_the_chat_history(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner)
    run, _ = _run_with_response(db_session, task, RunStatus.COMPLETE)
    normal = create_chat_session(
        db_session, description="mine", user_id=owner.id, persona_id=DEFAULT_PERSONA_ID
    )

    listed = get_chat_sessions_by_user(
        user_id=owner.id, deleted=False, db_session=db_session
    )

    assert [chat.id for chat in listed] == [normal.id]
    assert run.chat_session_id not in {chat.id for chat in listed}
    assert task.status == ScheduledTaskStatus.ACTIVE


def test_a_task_ask_ignores_the_owners_always_allow(
    db_session: Session,
    owner: User,
    cleanup: list[int],
) -> None:
    linked, _ = make_mcp_integration(
        db_session,
        server_url=f"https://ask-{uuid4().hex[:8]}.example.com/mcp",
        name=f"ask-{uuid4().hex[:8]}",
        tools=("send_report",),
    )
    cleanup.append(linked.id)
    give_access(
        db_session, [linked], installation_policy=PluginInstallationPolicy.REQUIRED
    )
    db_session.add(
        IntegrationActionPolicy(
            integration_id=linked.id,
            action="send_report",
            user_id=owner.id,
            policy=IntegrationActionPolicyValue.ALLOW,
        )
    )
    task = _task(
        db_session,
        owner,
        integrations=[
            IntegrationLinkConfiguration(
                integration_id=linked.id,
                action_settings=ActionSettings(default="ask"),
            )
        ],
    )
    run, _ = _run_with_response(db_session, task, RunStatus.RUNNING)
    chat_session_id = run.chat_session_id
    assert chat_session_id is not None

    def policy() -> EffectivePolicy:
        return resolve_chat_action_policy(
            db_session,
            integration=linked,
            action_key="send_report",
            user_id=owner.id,
            chat_session_id=chat_session_id,
        )

    assert policy() is EffectivePolicy.ASK

    mark_run_status(
        db_session=db_session, run_id=run.id, status=ScheduledTaskRunStatus.SUCCEEDED
    )
    db_session.commit()

    assert policy() is EffectivePolicy.ALLOW


def test_a_run_over_budget_fails_before_its_chat(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner)
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.MANUAL_RUN_NOW,
    )
    db_session.commit()

    def over_budget(_user: User) -> None:
        raise OnyxError(OnyxErrorCode.RATE_LIMITED, "Budget used up")

    with patch("onyx.scheduled_tasks.executor.check_token_rate_limits", over_budget):
        run_scheduled_task_logic(run.id)

    db_session.expire_all()
    assert run.status == ScheduledTaskRunStatus.FAILED
    assert run.chat_session_id is None
    assert "Budget used up" in (run.error_detail or "")
    assert _notification_links(db_session, owner) == [
        (NotificationType.SCHEDULED_TASK_FAILED, f"/app/scheduled-tasks/{task.id}")
    ]


def test_a_fire_does_not_cancel_a_run_that_an_approval_resumed(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner)
    run, response = _run_with_response(db_session, task, RunStatus.SUSPENDED)
    sync_chat_run__no_commit(db_session, run)
    db_session.commit()
    # The approval resumed the response on an API server; the run status has
    # not followed yet.
    response.response_status = RunStatus.RUNNING
    db_session.commit()
    cache = get_cache_backend()
    cache.set(_owner_key(response.id), "{}", ex=60)
    try:
        _cancel_parked_runs(
            db_session,
            POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            [run],
            ScheduledTaskErrorClass.SUPERSEDED_BY_NEXT_FIRE,
        )
        db_session.commit()
    finally:
        cache.delete(_owner_key(response.id))

    db_session.expire_all()
    assert response.response_status == RunStatus.RUNNING
    assert run.status == ScheduledTaskRunStatus.RUNNING


def test_deleting_a_running_run_chat_cancels_the_run(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner, due=True)
    run, _ = _run_with_response(db_session, task, RunStatus.RUNNING)
    assert run.chat_session_id is not None
    delete_chat_session(owner.id, run.chat_session_id, db_session, hard_delete=True)

    sent = _dispatch_with_fake_broker()

    db_session.expire_all()
    assert run.status == ScheduledTaskRunStatus.CANCELLED
    assert run.error_class == "user_cancelled"
    assert len(sent) == 1


def test_a_run_of_a_deactivated_owner_fails_before_its_chat(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner)
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.MANUAL_RUN_NOW,
    )
    owner.is_active = False
    db_session.commit()
    try:
        run_scheduled_task_logic(run.id)
    finally:
        owner.is_active = True
        db_session.commit()

    db_session.expire_all()
    assert run.status == ScheduledTaskRunStatus.FAILED
    assert run.chat_session_id is None
    assert "can no longer chat" in (run.error_detail or "")


def test_a_fire_skips_while_a_parked_run_cannot_be_cancelled(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner, due=True)
    parked, response = _run_with_response(db_session, task, RunStatus.SUSPENDED)
    sync_chat_run__no_commit(db_session, parked)
    db_session.commit()
    # The response saved SUSPENDED but its owner has not let go yet.
    cache = get_cache_backend()
    cache.set(_owner_key(response.id), "{}", ex=60)
    try:
        sent = _dispatch_with_fake_broker()
    finally:
        cache.delete(_owner_key(response.id))

    db_session.expire_all()
    statuses = sorted(
        run.status
        for run in db_session.scalars(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task.id)
        )
    )
    assert parked.status == ScheduledTaskRunStatus.AWAITING_APPROVAL
    assert statuses == sorted(
        [ScheduledTaskRunStatus.AWAITING_APPROVAL, ScheduledTaskRunStatus.SKIPPED]
    )
    assert sent == []


def test_a_turn_stopped_at_the_chat_deadline_fails_its_run(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    run, _ = _run_with_response(
        db_session,
        _task(db_session, owner),
        RunStatus.CANCELLED,
        failure=RunFailure(
            kind=RunFailureKind.DEADLINE,
            message="The run was stopped at its deadline.",
        ),
    )

    sync_chat_run__no_commit(db_session, run)
    db_session.commit()

    db_session.refresh(run)
    assert run.status == ScheduledTaskRunStatus.FAILED
    assert run.error_class == "timeout"
    assert _notifications(db_session, owner) == [NotificationType.SCHEDULED_TASK_FAILED]


def _task_runs(db_session: Session, task: ScheduledTask) -> list[ScheduledTaskRun]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task.id)
        )
    )


def test_a_queued_run_fails_only_after_the_scheduled_residency(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner)
    now = datetime.now(timezone.utc)
    waiting = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
    )
    waiting.started_at = now - timedelta(minutes=30)
    stuck = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
    )
    stuck.started_at = now - timedelta(seconds=RUN_EXPIRES_SECONDS + 60)
    db_session.commit()

    cleanup_stuck_scheduled_runs.run(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE  # ty: ignore[invalid-argument-type]
    )

    db_session.expire_all()
    assert waiting.status == ScheduledTaskRunStatus.QUEUED
    assert stuck.status == ScheduledTaskRunStatus.FAILED
    assert stuck.error_class == ScheduledTaskErrorClass.STUCK


def test_a_fire_sends_a_queued_prior_run_again(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner, due=True)
    queued = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
    )
    old_started_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    queued.started_at = old_started_at
    db_session.commit()

    sent = _dispatch_with_fake_broker()

    runs = _task_runs(db_session, task)
    assert [run.id for run in runs] == [queued.id]
    assert runs[0].status == ScheduledTaskRunStatus.QUEUED
    assert runs[0].started_at > old_started_at + timedelta(minutes=19)
    assert task.next_run_at is not None
    assert task.next_run_at > datetime.now(timezone.utc)
    assert len(sent) == 1
    message = sent[0]
    assert message["name"] == OnyxCeleryTask.SCHEDULED_TASKS_RUN
    assert message["kwargs"] == {
        "run_id": str(queued.id),
        "tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
    }
    assert message["queue"] == OnyxCeleryQueues.SCHEDULED_TASKS
    assert message["priority"] == OnyxCeleryPriority.MEDIUM
    assert message["expires"] == RUN_EXPIRES_SECONDS


def test_a_fire_skips_while_a_prior_run_is_running(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner, due=True)
    running, response = _run_with_response(db_session, task, RunStatus.RUNNING)
    # A live worker owns the response.
    cache = get_cache_backend()
    cache.set(_owner_key(response.id), "{}", ex=60)
    try:
        sent = _dispatch_with_fake_broker()
    finally:
        cache.delete(_owner_key(response.id))

    runs = {run.id: run for run in _task_runs(db_session, task)}
    assert runs.pop(running.id).status == ScheduledTaskRunStatus.RUNNING
    [skipped] = runs.values()
    assert skipped.status == ScheduledTaskRunStatus.SKIPPED
    assert skipped.skip_reason == ScheduledTaskSkipReason.PRIOR_IN_FLIGHT
    assert sent == []


def test_the_stuck_sweep_skips_a_run_that_a_fire_is_requeuing(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner)
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
    )
    run.started_at = datetime.now(timezone.utc) - timedelta(
        seconds=RUN_EXPIRES_SECONDS + 60
    )
    db_session.commit()
    stuck_after = timedelta(seconds=RUN_EXPIRES_SECONDS)

    # A dispatch tick holds the run's lock while it requeues it.
    with get_session_with_current_tenant() as dispatch_session:
        requeue_queued_run__no_commit(
            dispatch_session, task.id, datetime.now(timezone.utc)
        )
        stuck = find_stuck_runs(db_session=db_session, queued_older_than=stuck_after)
        assert run.id not in {candidate.id for candidate in stuck}
        db_session.rollback()
        dispatch_session.commit()

    stuck = find_stuck_runs(db_session=db_session, queued_older_than=stuck_after)
    assert run.id not in {candidate.id for candidate in stuck}
    db_session.rollback()


def test_a_run_counts_its_time_from_its_start_not_its_queue_time(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner)
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
    )
    run.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.commit()

    before_start = datetime.now(timezone.utc)
    assert _start_run(run.id) is not None
    db_session.expire_all()
    # The response does not exist yet: the turn has not begun.
    _sync_chat_runs(
        db_session, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, datetime.now(timezone.utc)
    )
    db_session.commit()

    db_session.expire_all()
    assert run.status == ScheduledTaskRunStatus.RUNNING
    assert run.started_at >= before_start


def test_a_started_run_without_a_response_fails_after_the_start_limit(
    db_session: Session,
    owner: User,
    cleanup: list[int],  # noqa: ARG001
) -> None:
    task = _task(db_session, owner)
    now = datetime.now(timezone.utc)
    runs: list[ScheduledTaskRun] = []
    for age in (timedelta(minutes=1), NO_RESPONSE_OLDER_THAN + timedelta(minutes=1)):
        chat = create_chat_session(
            db_session,
            description=task.name,
            user_id=task.user_id,
            persona_id=DEFAULT_PERSONA_ID,
        )
        run = insert_run(
            db_session=db_session,
            task_id=task.id,
            trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
        )
        mark_run_status(
            db_session=db_session,
            run_id=run.id,
            status=ScheduledTaskRunStatus.RUNNING,
            chat_session_id=chat.id,
            started_at=now - age,
        )
        runs.append(run)
    db_session.commit()

    _sync_chat_runs(db_session, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, now)
    db_session.commit()

    db_session.expire_all()
    fresh, stuck = runs
    assert fresh.status == ScheduledTaskRunStatus.RUNNING
    assert stuck.status == ScheduledTaskRunStatus.FAILED
    assert stuck.error_class == ScheduledTaskErrorClass.STUCK
