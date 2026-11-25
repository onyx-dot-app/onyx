"""Approval cards for the app requests of a command in the chat's VM.

A command's app requests carry its command ID to the egress proxy
(`harness_sandbox.py:command_proxy_user`). While an exec_command or
write_stdin call waits on the command, `CommandApprovals` marks the command
as in the foreground, so the proxy holds an Ask request of the command
instead of refusing it (`sandbox_proxy/addons/gate.py`). A thread shows each
held request as an approval card on the call, and its end as the card's
resolution. The user decides through `POST /chat/approvals/{id}/decision`,
which wakes the proxy. The call does not yield while a card waits (`holds`).

When the last call that waits on the command ends, the command leaves the
foreground and its requests that still wait end: rejected by the user on a
Stop, expired otherwise. Each card that a call shows ends with its request's
outcome; the renderer closes the cards of a stopped call.

Only a call that a client streams holds requests (`ToolContext.
shows_command_approvals`); a background agent or a non-streaming caller
holds none, so the proxy refuses the command's Ask requests.
"""

import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

from onyx.agents.tools import ToolProgress, ToolUpdate
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db import action_approval
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
from onyx.db.models import ActionApproval
from onyx.external_apps.matching.engine import (
    MatchedAction,
    actions_requiring_approval,
)
from onyx.llm.cancellation import AgentCancelled
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.build.configs import SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
from onyx.tools.tool_implementations.sandbox.models import (
    CommandApprovalOutcome,
    CommandApprovalRequest,
    CommandApprovalResolved,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The watcher blocks this long on the announce list, then renews the
# foreground mark and reads the decisions of the cards it shows.
_POLL_SECONDS = 1
_JOIN_SECONDS = 5.0

# The calls of this process that wait on each command. Parallel write_stdin
# calls can wait on one command; only the last one to end ends its requests.
_WAITING_LOCK = threading.Lock()
_waiting: dict[UUID, int] = {}


def _outcome(row: ActionApproval) -> CommandApprovalOutcome:
    if row.decision == ApprovalDecision.APPROVED:
        return (
            "approved_for_command"
            if row.decided_via == ApprovalDecidedVia.COMMAND_GRANT
            else "approved"
        )
    if row.decision == ApprovalDecision.REJECTED:
        return "rejected"
    return "cancelled"


def _card(row: ActionApproval) -> CommandApprovalRequest:
    actions = [MatchedAction.model_validate(a) for a in row.actions]
    asked = set(actions_requiring_approval(actions))
    names = [a.display_name for a in actions if a.action_type in asked]
    return CommandApprovalRequest(
        approval_id=str(row.approval_id),
        app_name=row.app_name,
        action_type=actions[0].action_type,
        display_name=", ".join(names) or actions[0].display_name,
        arguments=row.payload,
        can_approve_for_command=bool(approval_cache.command_grant_actions(row.actions)),
    )


class CommandApprovals:
    """The proxy approvals of the command that one call waits on. Implements
    `harness_base.CommandHold`; the call calls `end` once it returns."""

    def __init__(
        self, *, tenant_id: str, chat_session_id: UUID, update: ToolUpdate
    ) -> None:
        self._tenant_id = tenant_id
        self._chat_session_id = chat_session_id
        self._update = update
        self._lock = threading.Lock()
        self._command_id: UUID | None = None
        # Cards on screen whose request still waits.
        self._shown: set[UUID] = set()
        # Cards that ended; a stale pending read must not show them again.
        self._resolved: set[UUID] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _cache(self) -> CacheBackend:
        return get_cache_backend(tenant_id=self._tenant_id)

    def begin(self, command_id: UUID) -> None:
        self._command_id = command_id
        with _WAITING_LOCK:
            _waiting[command_id] = _waiting.get(command_id, 0) + 1
        try:
            approval_cache.mark_command_foreground(
                command_id, self._chat_session_id, self._cache()
            )
        except Exception:
            # The proxy then refuses the command's Ask requests.
            logger.exception("command_foreground_mark_failed command=%s", command_id)
        self._thread = threading.Thread(
            target=self._watch,
            args=(command_id,),
            name=f"command-approvals-{command_id.hex[:8]}",
            daemon=True,
        )
        self._thread.start()

    def holds(self) -> bool:
        """A request of the command waits for the user. Shows a waiting
        request whose announcement the watcher missed."""
        command_id = self._command_id
        if command_id is None:
            return False
        try:
            with get_session_with_tenant(tenant_id=self._tenant_id) as db:
                rows = action_approval.list_command_action_approvals(
                    db,
                    chat_session_id=self._chat_session_id,
                    command_id=command_id,
                    pending_only=True,
                    # Older rows wait on no proxy (the proxy's wait timeout).
                    created_after=datetime.now(timezone.utc)
                    - timedelta(seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS),
                )
            for row in rows:
                self._show(row)
        except AgentCancelled:
            return False
        except Exception:
            logger.exception("command_approvals_read_failed command=%s", command_id)
            return False
        return bool(rows)

    def end(self, *, cancelled: bool) -> None:
        """The call returned. When no other call waits on the command, it
        leaves the foreground and its requests that wait end."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=_JOIN_SECONDS)
        command_id = self._command_id
        if command_id is None:
            return
        decision = ApprovalDecision.REJECTED if cancelled else ApprovalDecision.EXPIRED
        ended: list[UUID] = []
        # The cleanup runs under the lock, so a new call of the command marks
        # it and holds its requests only after the cleanup.
        with _WAITING_LOCK:
            _waiting[command_id] -= 1
            if _waiting[command_id] == 0:
                del _waiting[command_id]
                ended = self._end_command(command_id, decision)
        # Every card on screen ends with its request's outcome, also one that
        # the user decided after the watcher's last read.
        with self._lock:
            shown = set(self._shown)
            self._shown.clear()
        if not shown:
            return
        try:
            with get_session_with_tenant(tenant_id=self._tenant_id) as db:
                rows = action_approval.list_command_action_approvals(
                    db,
                    chat_session_id=self._chat_session_id,
                    command_id=command_id,
                    approval_ids=shown,
                )
            for row in rows:
                self._report(
                    CommandApprovalResolved(
                        approval_id=str(row.approval_id),
                        outcome="cancelled"
                        if row.approval_id in ended
                        else _outcome(row),
                    )
                )
        except AgentCancelled:
            # A stopped call reports nothing more; the renderer closes its
            # open cards (`chat/renderer.py:ToolRenderer.complete`).
            pass
        except Exception:
            logger.exception("command_approvals_report_failed command=%s", command_id)

    def _end_command(self, command_id: UUID, decision: ApprovalDecision) -> list[UUID]:
        """Take the command out of the foreground and end its requests that
        wait with `decision`; the IDs of the requests that it ended."""
        cache: CacheBackend | None = None
        try:
            cache = self._cache()
            approval_cache.clear_command_foreground(command_id, cache)
        except Exception:
            logger.exception("command_foreground_clear_failed command=%s", command_id)
        ended: list[UUID] = []
        try:
            with get_session_with_tenant(tenant_id=self._tenant_id) as db:
                pending = action_approval.list_command_action_approvals(
                    db,
                    chat_session_id=self._chat_session_id,
                    command_id=command_id,
                    pending_only=True,
                )
                ended = [
                    row.approval_id
                    for row in pending
                    if action_approval.try_record_decision(
                        db,
                        approval_id=row.approval_id,
                        decision=decision,
                        decided_via=ApprovalDecidedVia.USER
                        if decision == ApprovalDecision.REJECTED
                        else None,
                    )
                ]
                db.commit()
        except Exception:
            logger.exception("command_approvals_end_failed command=%s", command_id)
        for approval_id in ended:
            try:
                if cache is not None:
                    approval_cache.send_wake(approval_id, decision, cache)
            except Exception:
                logger.warning("command_approval_wake_failed approval=%s", approval_id)
        return ended

    def _watch(self, command_id: UUID) -> None:
        cache = self._cache()
        while not self._stop.is_set():
            try:
                approval_cache.mark_command_foreground(
                    command_id, self._chat_session_id, cache
                )
                announced = approval_cache.pop_announcement(
                    command_id, _POLL_SECONDS, cache
                )
                self._poll(command_id, announced)
            except AgentCancelled:
                return
            except Exception:
                logger.exception(
                    "command_approvals_watch_failed command=%s", command_id
                )
                self._stop.wait(_POLL_SECONDS)

    def _poll(self, command_id: UUID, announced: UUID | None) -> None:
        with self._lock:
            ids = set(self._shown)
        if announced is not None:
            ids.add(announced)
        if not ids:
            return
        with get_session_with_tenant(tenant_id=self._tenant_id) as db:
            rows = action_approval.list_command_action_approvals(
                db,
                chat_session_id=self._chat_session_id,
                command_id=command_id,
                approval_ids=ids,
            )
        for row in rows:
            self._show(row)
            with self._lock:
                resolved = row.decision is not None and row.approval_id in self._shown
                if resolved:
                    self._shown.discard(row.approval_id)
                    self._resolved.add(row.approval_id)
            if resolved:
                self._report(
                    CommandApprovalResolved(
                        approval_id=str(row.approval_id), outcome=_outcome(row)
                    )
                )

    def _show(self, row: ActionApproval) -> None:
        """Show the card of a waiting request once."""
        with self._lock:
            if (
                row.decision is not None
                or row.approval_id in self._shown
                or row.approval_id in self._resolved
            ):
                return
            self._shown.add(row.approval_id)
        self._report(_card(row))

    def _report(
        self, details: CommandApprovalRequest | CommandApprovalResolved
    ) -> None:
        try:
            self._update(ToolProgress(details=details))
        except AgentCancelled:
            raise
        except Exception:
            logger.exception("command_approval_report_failed")
