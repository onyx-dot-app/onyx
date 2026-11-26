"""An app request of a command in a chat's VM, from the gate's hold to the
card on the call and the user's decision, on real Postgres rows and Redis.

The gate side is `GateAddon._persist_approval_row` and `_await_decision`, the
call side is `CommandApprovals`, and the decision goes through the chat
decision route.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.agents.tools import ToolProgress
from onyx.cache.factory import get_cache_backend
from onyx.cache.postgres_backend import PostgresCacheBackend
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.chat import create_chat_session, delete_chat_session
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import (
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
    IntegrationActionPolicyValue,
    IntegrationKind,
    PluginInstallationPolicy,
)
from onyx.db.models import (
    ActionApproval,
    CacheStore,
    ChatSession,
    Integration,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
)
from onyx.sandbox_proxy import approval_cache
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import parse_destination_policy
from onyx.sandbox_proxy.sandbox_identity.models import SessionContext
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.features.build.configs import SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
from onyx.server.query_and_chat import command_approvals
from onyx.server.query_and_chat.chat_backend import decide_approval
from onyx.server.query_and_chat.models import ChatApprovalDecisionRequest
from onyx.tools.tool_implementations.sandbox import (
    command_approvals as command_approvals_tool,
)
from onyx.tools.tool_implementations.sandbox.command_approvals import (
    CommandApprovals,
)
from onyx.tools.tool_implementations.sandbox.models import (
    CommandApprovalRequest,
    CommandApprovalResolved,
)
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.craft.db_helpers import (
    app_integration_id,
    make_external_app,
)
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    set_policy,
)

_WAIT_S = 10.0


class _Chat(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    user: User
    chat_session_id: UUID
    integration_id: int


@pytest.fixture
def chat(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    make_test_user: MakeTestUser,
) -> Generator[_Chat, None, None]:
    user = make_test_user("chat_command_approvals")
    app = make_external_app(db_session, auth_template={})
    integration_id = app_integration_id(db_session, app)
    # The default agent uses each integration the user runs.
    integration = db_session.get(Integration, integration_id)
    assert integration is not None
    give_access(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    db_session.commit()
    chat_session = create_chat_session(
        db_session, "command", user.id, DEFAULT_PERSONA_ID
    )
    # Every call that a test begins ends here, also when the test fails.
    started: list[CommandApprovals] = []
    begin = CommandApprovals.begin

    def recording_begin(self: CommandApprovals, command_id: UUID) -> None:
        started.append(self)
        begin(self, command_id)

    monkeypatch.setattr(CommandApprovals, "begin", recording_begin)
    held: list[_HeldRequest] = []
    init = _HeldRequest.__init__

    def recording_init(self: _HeldRequest, *args: Any) -> None:
        init(self, *args)
        held.append(self)

    monkeypatch.setattr(_HeldRequest, "__init__", recording_init)
    try:
        yield _Chat(
            user=user,
            chat_session_id=chat_session.id,
            integration_id=integration_id,
        )
    finally:
        for approvals in started:
            if not approvals._stop.is_set():
                approvals.end(cancelled=False)
        cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA)
        # Every proxy wait that a test starts ends here; a repeated wake of a
        # decided request changes nothing.
        for request in held:
            approval_cache.send_wake(
                request.approval_id, ApprovalDecision.EXPIRED, cache
            )
            request.result()
        for approvals in started:
            if approvals._command_id is not None:
                approval_cache.drop_command_grants(approvals._command_id, cache)
        db_session.rollback()
        db_session.execute(delete(ChatSession).where(ChatSession.id == chat_session.id))
        db_session.commit()
        delete_integrations(db_session, [integration_id])


def _matched(
    integration_id: int, action_type: str = "issues.create"
) -> AllMatchedActions:
    return AllMatchedActions(
        actions=(
            MatchedAction(
                action_type=action_type,
                display_name="Create an issue",
                description="Create an issue.",
                policy=ActionPolicy.ASK,
            ),
        ),
        target=GatedTarget(
            integration_id=integration_id,
            kind=IntegrationKind.API,
            app_name="Tracker",
        ),
        payload={},
    )


def _gate() -> GateAddon:
    return GateAddon(
        destination_policy=parse_destination_policy(""),
        identity=MagicMock(),
        request_evaluator=MagicMock(),
        cache_factory=lambda tenant_id: get_cache_backend(tenant_id=tenant_id),
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
    )


def _ctx(chat: _Chat, command_id: UUID) -> SessionContext:
    return SessionContext(
        session_id=chat.chat_session_id,
        chat_command_id=command_id,
        user_id=chat.user.id,
        sandbox_id=uuid4(),
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        sandbox_name="vm-test",
        sandbox_ip="127.0.0.1",
    )


class _HeldRequest:
    """One request that the gate holds: its row and the gate's wait, which
    runs in a thread as the proxy's event loop would."""

    def __init__(
        self, gate: GateAddon, ctx: SessionContext, matched: AllMatchedActions
    ) -> None:
        self.approval_id = gate._persist_approval_row(
            ctx, matched, {"method": "POST", "path": "/issues"}
        )
        self.decision: ApprovalDecision | None = None
        self._thread = threading.Thread(
            target=self._wait, args=(gate, ctx, matched), daemon=True
        )
        self._thread.start()

    def _wait(
        self, gate: GateAddon, ctx: SessionContext, matched: AllMatchedActions
    ) -> None:
        self.decision = asyncio.run(
            gate._await_decision(self.approval_id, ctx, matched)
        )

    def result(self) -> ApprovalDecision | None:
        self._thread.join(timeout=_WAIT_S)
        return self.decision


class _Reports:
    """The progress that the call reports, from the watcher's thread."""

    def __init__(self) -> None:
        self.details: list[BaseModel] = []
        self._changed = threading.Condition()

    def __call__(self, progress: ToolProgress) -> None:
        assert progress.details is not None
        with self._changed:
            self.details.append(progress.details)
            self._changed.notify_all()

    def wait_for(self, check: Callable[[], bool]) -> None:
        with self._changed:
            assert self._changed.wait_for(check, timeout=_WAIT_S), "timed out"

    def cards(self) -> list[CommandApprovalRequest]:
        return [d for d in self.details if isinstance(d, CommandApprovalRequest)]

    def outcomes(self) -> dict[str, str]:
        return {
            d.approval_id: d.outcome
            for d in self.details
            if isinstance(d, CommandApprovalResolved)
        }


def _decide(
    db_session: Session, chat: _Chat, approval_id: UUID, choice: ApprovalChoice
) -> ApprovalDecidedVia:
    response = decide_approval(
        approval_id,
        ChatApprovalDecisionRequest(decision=choice),
        request=MagicMock(),
        user=chat.user,
        db_session=db_session,
    )
    assert response.continuation is None
    return response.decided_via


def _command(chat: _Chat) -> tuple[UUID, _Reports, CommandApprovals]:
    command_id = uuid4()
    reports = _Reports()
    approvals = CommandApprovals(
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        chat_session_id=chat.chat_session_id,
        update=reports,
    )
    approvals.begin(command_id)
    return command_id, reports, approvals


@pytest.mark.parametrize(
    ("choice", "expected", "outcome"),
    [
        (ApprovalChoice.APPROVE_ONCE, ApprovalDecision.APPROVED, "approved"),
        # Clients that know no command scope offer a chat approval.
        (ApprovalChoice.APPROVE_SESSION, ApprovalDecision.APPROVED, "approved"),
        (ApprovalChoice.REJECT, ApprovalDecision.REJECTED, "rejected"),
    ],
)
def test_a_held_request_shows_a_card_and_the_decision_wakes_the_gate(
    db_session: Session,
    chat: _Chat,
    choice: ApprovalChoice,
    expected: ApprovalDecision,
    outcome: str,
) -> None:
    command_id, reports, approvals = _command(chat)
    gate = _gate()
    ctx = _ctx(chat, command_id)
    assert gate._command_in_foreground(ctx)
    try:
        held = _HeldRequest(gate, ctx, _matched(chat.integration_id))

        reports.wait_for(lambda: bool(reports.cards()))
        card = reports.cards()[0]
        assert card.approval_id == str(held.approval_id)
        assert card.app_name == "Tracker"
        assert card.display_name == "Create an issue"
        assert card.arguments == {"method": "POST", "path": "/issues"}
        assert card.can_approve_for_command
        assert approvals.holds()

        _decide(db_session, chat, held.approval_id, choice)

        assert held.result() == expected
        reports.wait_for(lambda: str(held.approval_id) in reports.outcomes())
        assert reports.outcomes()[str(held.approval_id)] == outcome
        assert not approvals.holds()
    finally:
        approvals.end(cancelled=False)
    assert not gate._command_in_foreground(ctx)


def test_approve_for_the_command_covers_the_same_action_until_the_command_exits(
    db_session: Session, chat: _Chat
) -> None:
    command_id, reports, approvals = _command(chat)
    gate = _gate()
    ctx = _ctx(chat, command_id)
    matched = _matched(chat.integration_id)
    try:
        first = _HeldRequest(gate, ctx, matched)
        second = _HeldRequest(gate, ctx, matched)
        reports.wait_for(lambda: len(reports.cards()) == 2)

        assert (
            _decide(db_session, chat, first.approval_id, ApprovalChoice.APPROVE_COMMAND)
            == ApprovalDecidedVia.COMMAND_GRANT
        )

        # The grant also approved the request that waited with it.
        assert first.result() == ApprovalDecision.APPROVED
        assert second.result() == ApprovalDecision.APPROVED
        reports.wait_for(lambda: len(reports.outcomes()) == 2)
        assert set(reports.outcomes().values()) == {"approved_for_command"}
        # A later request of the action needs no card; another action does.
        assert gate._session_grant(db_session, ctx, matched)
        assert not gate._session_grant(
            db_session, ctx, _matched(chat.integration_id, "issues.delete")
        )
    finally:
        approvals.end(cancelled=False)
    # The exited command is no longer in the foreground, so the gate refuses
    # its Ask requests before it checks a grant.
    assert not gate._command_in_foreground(ctx)


def test_a_stop_refuses_the_requests_that_wait(
    db_session: Session, chat: _Chat
) -> None:
    command_id, reports, approvals = _command(chat)
    gate = _gate()
    ctx = _ctx(chat, command_id)
    held = _HeldRequest(gate, ctx, _matched(chat.integration_id))
    reports.wait_for(lambda: bool(reports.cards()))

    approvals.end(cancelled=True)

    assert held.result() == ApprovalDecision.REJECTED
    assert reports.outcomes() == {str(held.approval_id): "cancelled"}
    db_session.expire_all()
    row = db_session.get(ActionApproval, held.approval_id)
    assert row is not None and row.decided_via == ApprovalDecidedVia.USER
    assert not gate._command_in_foreground(ctx)


def test_the_end_reports_a_decision_that_the_watcher_did_not_read(
    db_session: Session, chat: _Chat
) -> None:
    """The command exits right after the approval: the card still ends with
    the decision."""
    command_id, reports, approvals = _command(chat)
    gate = _gate()
    held = _HeldRequest(gate, _ctx(chat, command_id), _matched(chat.integration_id))
    reports.wait_for(lambda: bool(reports.cards()))
    # The watcher stops before it reads the decision.
    approvals._stop.set()
    assert approvals._thread is not None
    approvals._thread.join(timeout=_WAIT_S)

    _decide(db_session, chat, held.approval_id, ApprovalChoice.APPROVE_ONCE)
    approvals.end(cancelled=False)

    assert held.result() == ApprovalDecision.APPROVED
    assert reports.outcomes() == {str(held.approval_id): "approved"}


def test_a_call_that_ends_leaves_the_requests_to_another_call_of_the_command(
    db_session: Session, chat: _Chat
) -> None:
    """Two parallel write_stdin calls wait on one command: the first to end
    leaves its requests waiting for the other."""
    command_id, reports, first = _command(chat)
    second = CommandApprovals(
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        chat_session_id=chat.chat_session_id,
        update=reports,
    )
    second.begin(command_id)
    gate = _gate()
    ctx = _ctx(chat, command_id)
    try:
        held = _HeldRequest(gate, ctx, _matched(chat.integration_id))
        reports.wait_for(lambda: bool(reports.cards()))

        first.end(cancelled=False)

        assert gate._command_in_foreground(ctx)
        assert second.holds()
        _decide(db_session, chat, held.approval_id, ApprovalChoice.APPROVE_ONCE)
        assert held.result() == ApprovalDecision.APPROVED
    finally:
        second.end(cancelled=False)
    assert not gate._command_in_foreground(ctx)


def test_a_call_that_begins_during_the_cleanup_marks_after_it(
    chat: _Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last call's cleanup clears the foreground mark: a call of the
    command that begins meanwhile marks it only after the cleanup."""
    command_id, _reports, first = _command(chat)
    second = CommandApprovals(
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        chat_session_id=chat.chat_session_id,
        update=_Reports(),
    )
    log: list[str] = []
    cleaning = threading.Event()
    marked = threading.Event()
    end_command = CommandApprovals._end_command
    mark = command_approvals_tool.approval_cache.mark_command_foreground

    def paused_end_command(self: CommandApprovals, *args: Any, **kwargs: Any) -> Any:
        cleaning.set()
        # A begin that does not wait for the cleanup marks within this time.
        marked.wait(timeout=2)
        ended = end_command(self, *args, **kwargs)
        log.append("cleaned")
        return ended

    def logged_mark(*args: Any) -> None:
        mark(*args)
        if cleaning.is_set():
            log.append("marked")
            marked.set()

    monkeypatch.setattr(CommandApprovals, "_end_command", paused_end_command)
    monkeypatch.setattr(
        command_approvals_tool.approval_cache, "mark_command_foreground", logged_mark
    )
    ending = threading.Thread(target=first.end, kwargs={"cancelled": False})
    ending.start()
    assert cleaning.wait(_WAIT_S)
    beginning = threading.Thread(target=second.begin, args=(command_id,))
    beginning.start()
    ending.join(timeout=_WAIT_S)
    beginning.join(timeout=_WAIT_S)
    assert log[:2] == ["cleaned", "marked"]


def test_a_slow_cleanup_does_not_block_another_command(
    chat: _Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cleanup of one command does not hold up a call of another."""
    _command_id, _reports, first = _command(chat)
    cleaning = threading.Event()
    release = threading.Event()
    end_command = CommandApprovals._end_command

    def blocked_end_command(self: CommandApprovals, *args: Any, **kwargs: Any) -> Any:
        cleaning.set()
        release.wait(timeout=_WAIT_S)
        return end_command(self, *args, **kwargs)

    monkeypatch.setattr(CommandApprovals, "_end_command", blocked_end_command)
    other = CommandApprovals(
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        chat_session_id=chat.chat_session_id,
        update=_Reports(),
    )
    ending = threading.Thread(target=first.end, kwargs={"cancelled": False})
    ending.start()
    try:
        assert cleaning.wait(_WAIT_S)
        beginning = threading.Thread(target=other.begin, args=(uuid4(),))
        beginning.start()
        beginning.join(timeout=_WAIT_S / 2)
        assert not beginning.is_alive()
    finally:
        release.set()
        ending.join(timeout=_WAIT_S)
    other.end(cancelled=False)


def _matched_actions(integration_id: int, *action_types: str) -> AllMatchedActions:
    return _matched(integration_id).model_copy(
        update={
            "actions": tuple(
                MatchedAction(
                    action_type=action_type,
                    display_name=action_type,
                    description=action_type,
                    policy=ActionPolicy.ASK,
                )
                for action_type in action_types
            )
        }
    )


def test_the_command_grants_together_cover_a_waiting_request(
    db_session: Session, chat: _Chat
) -> None:
    """The proxy checks a request against all the command's grants, so the
    decision that completes them also approves a waiting request."""
    command_id, reports, approvals = _command(chat)
    gate = _gate()
    ctx = _ctx(chat, command_id)
    create, remove = "issues.create", "issues.delete"
    try:
        first = _HeldRequest(gate, ctx, _matched_actions(chat.integration_id, create))
        both = _HeldRequest(
            gate, ctx, _matched_actions(chat.integration_id, create, remove)
        )
        last = _HeldRequest(gate, ctx, _matched_actions(chat.integration_id, remove))
        reports.wait_for(lambda: len(reports.cards()) == 3)

        _decide(db_session, chat, first.approval_id, ApprovalChoice.APPROVE_COMMAND)
        assert first.result() == ApprovalDecision.APPROVED
        _decide(db_session, chat, last.approval_id, ApprovalChoice.APPROVE_COMMAND)

        assert last.result() == ApprovalDecision.APPROVED
        assert both.result() == ApprovalDecision.APPROVED
    finally:
        approvals.end(cancelled=False)


def test_a_command_grant_is_saved_before_the_scan_of_waiting_requests(
    db_session: Session, chat: _Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request that checks the grant before it is saved has committed its
    row, so the scan after the save approves it. The decision is committed
    before the scan locks other rows, so two decisions cannot deadlock."""
    command_id = uuid4()
    gate = _gate()
    approval_id = gate._persist_approval_row(
        _ctx(chat, command_id), _matched(chat.integration_id), {}
    )
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA)
    seen: list[tuple[bool, ApprovalDecision | None]] = []
    original = command_approvals.action_approval.list_pending_command_action_approvals

    def scan(db: Session, **kwargs: Any) -> list[ActionApproval]:
        with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as other:
            row = other.get(ActionApproval, approval_id)
            assert row is not None
            covered = approval_cache.command_grants_cover(
                command_id,
                chat.chat_session_id,
                chat.integration_id,
                ["issues.create"],
                cache,
            )
            seen.append((covered, row.decision))
        return original(db, **kwargs)

    monkeypatch.setattr(
        command_approvals.action_approval, "list_pending_command_action_approvals", scan
    )
    try:
        _decide(db_session, chat, approval_id, ApprovalChoice.APPROVE_COMMAND)
    finally:
        cache.delete_prefix(f"approval:command:{command_id}:")

    assert seen == [(True, ApprovalDecision.APPROVED)]


def test_a_command_grant_for_a_decided_request_grants_nothing(
    db_session: Session, chat: _Chat
) -> None:
    """A conflict saves no grant, so the command's later requests still ask."""
    command_id = uuid4()
    approval_id = _gate()._persist_approval_row(
        _ctx(chat, command_id), _matched(chat.integration_id), {}
    )
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA)
    _decide(db_session, chat, approval_id, ApprovalChoice.REJECT)
    try:
        with pytest.raises(OnyxError) as conflict:
            _decide(db_session, chat, approval_id, ApprovalChoice.APPROVE_COMMAND)
        assert conflict.value.error_code is OnyxErrorCode.CONFLICT
        assert not approval_cache.command_grants_cover(
            command_id,
            chat.chat_session_id,
            chat.integration_id,
            ["issues.create"],
            cache,
        )
    finally:
        cache.delete_prefix(f"approval:command:{command_id}:")


@pytest.mark.parametrize(
    "choice", [ApprovalChoice.APPROVE_ONCE, ApprovalChoice.APPROVE_COMMAND]
)
def test_approving_a_request_that_the_policies_now_block_saves_a_rejection(
    db_session: Session, chat: _Chat, choice: ApprovalChoice
) -> None:
    """The proxy refuses a request whose action an admin blocked while its
    card was open, so its approval is a rejection by the policy and grants
    nothing."""
    command_id = uuid4()
    approval_id = _gate()._persist_approval_row(
        _ctx(chat, command_id), _matched(chat.integration_id), {}
    )
    set_policy(
        db_session,
        chat.integration_id,
        "issues.create",
        IntegrationActionPolicyValue.BLOCKED,
    )
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA)
    try:
        response = decide_approval(
            approval_id,
            ChatApprovalDecisionRequest(decision=choice),
            request=MagicMock(),
            user=chat.user,
            db_session=db_session,
        )
        assert (response.decision, response.decided_via) == (
            ApprovalDecision.REJECTED,
            ApprovalDecidedVia.POLICY,
        )
        db_session.expire_all()
        row = db_session.get(ActionApproval, approval_id)
        assert row is not None and row.decision == ApprovalDecision.REJECTED
        assert not approval_cache.command_grants_cover(
            command_id,
            chat.chat_session_id,
            chat.integration_id,
            ["issues.create"],
            cache,
        )
    finally:
        cache.delete_prefix(f"approval:command:{command_id}:")


@pytest.mark.parametrize(
    ("case", "error_code"),
    [
        ("another_user", OnyxErrorCode.NOT_FOUND),
        ("expired", OnyxErrorCode.CONFLICT),
        ("always_asks", OnyxErrorCode.INVALID_INPUT),
    ],
)
def test_a_refused_decision_leaves_the_request_waiting(
    db_session: Session,
    chat: _Chat,
    make_test_user: MakeTestUser,
    case: str,
    error_code: OnyxErrorCode,
) -> None:
    """Only the chat's owner decides, only while the request waits, and a
    request that always asks cannot be approved for the command."""
    command_id = uuid4()
    action_type = "unspecified" if case == "always_asks" else "issues.create"
    approval_id = _gate()._persist_approval_row(
        _ctx(chat, command_id), _matched(chat.integration_id, action_type), {}
    )
    decider = chat.user
    if case == "another_user":
        decider = make_test_user("chat_command_approvals_other")
    if case == "expired":
        row = db_session.get(ActionApproval, approval_id)
        assert row is not None
        row.created_at = datetime.now(timezone.utc) - timedelta(
            seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS + 60
        )
        db_session.commit()
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA)
    try:
        with pytest.raises(OnyxError) as error:
            decide_approval(
                approval_id,
                ChatApprovalDecisionRequest(decision=ApprovalChoice.APPROVE_COMMAND),
                request=MagicMock(),
                user=decider,
                db_session=db_session,
            )
        assert error.value.error_code is error_code
        db_session.rollback()
        db_session.expire_all()
        row = db_session.get(ActionApproval, approval_id)
        assert row is not None and row.decision is None
        assert not approval_cache.command_grants_cover(
            command_id, chat.chat_session_id, chat.integration_id, [action_type], cache
        )
    finally:
        cache.delete_prefix(f"approval:command:{command_id}:")


def test_a_command_grant_that_the_cache_cannot_save_approves_only_this_request(
    db_session: Session, chat: _Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proxy sends a COMMAND_GRANT row only while the cache holds the
    grant, so without it the request is approved once and the command's
    other requests keep waiting for the user."""
    command_id = uuid4()
    gate = _gate()
    ctx = _ctx(chat, command_id)
    first = gate._persist_approval_row(ctx, _matched(chat.integration_id), {})
    second = gate._persist_approval_row(ctx, _matched(chat.integration_id), {})

    def fail(*_args: Any) -> None:
        raise RedisError("down")

    monkeypatch.setattr(command_approvals.approval_cache, "grant_command_actions", fail)

    assert (
        _decide(db_session, chat, first, ApprovalChoice.APPROVE_COMMAND)
        == ApprovalDecidedVia.USER
    )
    db_session.expire_all()
    first_row = db_session.get(ActionApproval, first)
    second_row = db_session.get(ActionApproval, second)
    assert first_row is not None
    assert (first_row.decision, first_row.decided_via) == (
        ApprovalDecision.APPROVED,
        ApprovalDecidedVia.USER,
    )
    assert second_row is not None and second_row.decision is None


def test_the_decided_request_wakes_before_the_scan_of_the_others(
    db_session: Session, chat: _Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed scan of the command's other requests still wakes the request
    that the user decided."""
    command_id = uuid4()
    gate = _gate()
    held = _HeldRequest(gate, _ctx(chat, command_id), _matched(chat.integration_id))

    def fail(*_args: Any, **_kwargs: Any) -> list[ActionApproval]:
        raise RuntimeError("scan failed")

    monkeypatch.setattr(
        command_approvals.action_approval, "list_pending_command_action_approvals", fail
    )
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA)
    try:
        with pytest.raises(RuntimeError):
            _decide(db_session, chat, held.approval_id, ApprovalChoice.APPROVE_COMMAND)
        assert held.result() == ApprovalDecision.APPROVED
    finally:
        cache.delete_prefix(f"approval:command:{command_id}:")


def test_a_failed_wake_does_not_stop_the_other_wakes(
    db_session: Session, chat: _Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    command_id = uuid4()
    gate = _gate()
    ctx = _ctx(chat, command_id)
    matched = _matched(chat.integration_id)
    first = _HeldRequest(gate, ctx, matched)
    second = _HeldRequest(gate, ctx, matched)
    third = _HeldRequest(gate, ctx, matched)
    send_wake = command_approvals.approval_cache.send_wake
    failed: list[UUID] = []

    def flaky(approval_id: UUID, decision: ApprovalDecision, cache: Any) -> None:
        if approval_id != first.approval_id and not failed:
            failed.append(approval_id)
            raise RedisError("down")
        send_wake(approval_id, decision, cache)

    monkeypatch.setattr(command_approvals.approval_cache, "send_wake", flaky)
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA)
    try:
        _decide(db_session, chat, first.approval_id, ApprovalChoice.APPROVE_COMMAND)
        woken = second if failed == [third.approval_id] else third
        assert first.result() == ApprovalDecision.APPROVED
        assert woken.result() == ApprovalDecision.APPROVED
    finally:
        cache.delete_prefix(f"approval:command:{command_id}:")


def test_command_grants_expire_on_the_postgres_cache(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Every grant row has the grant TTL."""
    cache = PostgresCacheBackend(POSTGRES_DEFAULT_SCHEMA)
    command_id, chat_session_id = uuid4(), uuid4()

    def rows() -> dict[str, CacheStore]:
        db_session.expire_all()
        return {row.key: row for row in db_session.scalars(select(CacheStore))}

    before = set(rows())
    approval_cache.grant_command_actions(
        command_id, chat_session_id, 7, ["issues.create", "issues.delete"], cache
    )
    try:
        added = [row for key, row in rows().items() if key not in before]
        assert added
        assert all(row.expires_at is not None for row in added)
        assert approval_cache.command_grants_cover(
            command_id, chat_session_id, 7, ["issues.create", "issues.delete"], cache
        )
    finally:
        cache.delete_prefix(f"approval:command:{command_id}:")


def test_a_hard_delete_of_the_chat_removes_its_command_approval_rows(
    db_session: Session, chat: _Chat
) -> None:
    command_id = uuid4()
    approval_id = _gate()._persist_approval_row(
        _ctx(chat, command_id),
        _matched(chat.integration_id),
        {"method": "POST", "path": "/issues"},
    )
    row = db_session.get(ActionApproval, approval_id)
    assert row is not None
    assert (row.session_id, row.chat_session_id, row.command_id) == (
        None,
        chat.chat_session_id,
        command_id,
    )

    delete_chat_session(
        chat.user.id, chat.chat_session_id, db_session, hard_delete=True
    )

    db_session.expire_all()
    assert db_session.get(ActionApproval, approval_id) is None
