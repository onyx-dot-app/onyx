"""Background executor for interactive Craft turns."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS, CacheBackend
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Sandbox
from onyx.db.users import fetch_user_by_id
from onyx.server.features.build.configs import (
    OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS,
)
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.sandbox import (
    get_sandbox_by_user_id,
    update_sandbox_heartbeat,
)
from onyx.server.features.build.interactive_turns.state import (
    TURN_STATUS_CANCELLED,
    TURN_STATUS_FAILED,
    TURN_STATUS_SUCCEEDED,
    InteractiveTurn,
    claim_turn_for_runner,
    finish_turn,
    get_active_turn,
    touch_turn,
)
from onyx.server.features.build.sandbox.event_schema import (
    ActivityTimeoutError,
    PromptResponse,
)
from onyx.server.features.build.sandbox.event_schema import Error as SandboxError
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.sandbox.models import PromptAttachment
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from onyx.server.features.build.session.interrupt_signal import (
    clear_interrupt,
    is_interrupt_requested,
)
from onyx.server.features.build.session.locks import session_creation_lock
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.sandbox_lifecycle import (
    HEALTH_PROBE_TIMEOUT_SECONDS,
)
from onyx.server.features.build.session.session_ready import (
    ensure_session_ready,
    session_runtime_intact,
)
from onyx.server.features.build.session.streaming import BuildStreamingState
from onyx.server.features.build.timeouts import (
    INTERACTIVE_TURN_HARD_CAP_SECONDS,
    INTERACTIVE_TURN_SOFT_BUDGET_SECONDS,
    PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
    PROMPT_SLOT_WAIT_OUT_ORPHAN_SECONDS,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)

logger = setup_logger()

MAX_TIMEOUT_CONTINUATIONS = 2
_TOOL_TIMEOUT_CONTINUATION_PROMPT = (
    "Your last step was cancelled — it exceeded the "
    f"{int(OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS)}s activity limit with no "
    "output. Don't just retry it; split the work into shorter steps or run it in "
    "the background, then continue."
)


_TURN_ERROR_SUFFIX = (
    "Files written to the workspace are saved — send a follow-up message to continue."
)


class _PromptOutcome(Enum):
    TERMINATED = auto()  # the turn was already finished; the caller returns
    TIMED_OUT = auto()  # step went silent; the caller re-prompts
    COMPLETED = auto()  # the opencode stream ended; run the terminal handling


@dataclass
class _PromptResult:
    outcome: _PromptOutcome
    final_event_seen: bool = False
    cancelled: bool = False


def _can_clear_interrupt_fence(
    *,
    cache: CacheBackend,
    turn_id: UUID,
    session_id: UUID,
    user_id: UUID,
    runner_id: str | None,
) -> bool:
    active_turn = get_active_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
    )
    if active_turn is None:
        return True
    return active_turn.turn_id == turn_id and (
        runner_id is None or active_turn.runner_id == runner_id
    )


def start_interactive_turn_runner(turn_id: UUID) -> None:
    """Run an interactive turn in this API process if Redis grants ownership."""
    tenant_id = get_current_tenant_id()

    def run() -> None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        turn: InteractiveTurn | None = None
        try:
            turn = claim_turn_for_runner(cache=get_cache_backend(), turn_id=turn_id)
            if turn is None:
                return

            run_claimed_interactive_build_turn(turn)
        except Exception:
            logger.exception("Interactive turn runner failed for turn %s", turn_id)
            if turn is not None:
                finish_turn(
                    cache=get_cache_backend(),
                    turn_id=turn.turn_id,
                    status=TURN_STATUS_FAILED,
                    error_detail="Interactive turn runner failed.",
                    runner_id=turn.runner_id,
                )
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    thread = threading.Thread(
        target=run,
        name=f"interactive-build-turn-{turn_id}",
        daemon=True,
    )
    thread.start()


def run_claimed_interactive_build_turn(
    turn: InteractiveTurn,
    *,
    budget_seconds: int = INTERACTIVE_TURN_HARD_CAP_SECONDS,
) -> None:
    """Execute a turn that this runner has already claimed in CacheBackend.

    ``budget_seconds`` is the hard cap; the soft wrap-up steer is sandbox-side
    (turn-budget plugin).
    """
    cache = get_cache_backend()
    runner_id = turn.runner_id
    try:
        _drive_interactive_turn(
            turn_id=turn.turn_id,
            session_id=turn.session_id,
            user_id=turn.user_id,
            prompt=turn.prompt,
            turn_index=turn.turn_index,
            attachments=turn.attachments,
            budget_seconds=budget_seconds,
            runner_id=runner_id,
            reclaimed=turn.reclaimed,
        )
    except Exception as exc:
        logger.exception(
            "Interactive turn %s failed before drive loop",
            turn.turn_id,
        )
        finish_turn(
            cache=cache,
            turn_id=turn.turn_id,
            status=TURN_STATUS_FAILED,
            error_detail=f"{type(exc).__name__}: {str(exc)[:950]}",
            runner_id=runner_id,
        )


def _ready_session_runtime(
    db_session: Session, session_id: UUID, user_id: UUID
) -> Sandbox:
    """The sandbox this turn runs in, with the session's workspace present.

    A settled session returns straight away; anything else — a sandbox the
    reaper took, a session never restored, a pod that died under a live record —
    is rebuilt through the same path and the same lock the restore endpoint
    uses, blocking, because the turn has nothing to do until the workspace is
    there.

    The pre-lock check is only a fast path: ``ensure_session_ready`` re-verifies
    everything (pod liveness included) under the lock, so it stays with this
    caller — its point is skipping the lock on the hot path, and lock
    acquisition is caller policy (the turn blocks; restore 409s).
    """
    session = get_build_session(session_id, user_id, db_session)
    sandbox = get_sandbox_by_user_id(db_session, user_id)
    if sandbox is not None and session_runtime_intact(session, sandbox):
        # The reaper decides from this timestamp, and the stream only starts
        # refreshing it after the prompt slot and the send.
        update_sandbox_heartbeat(db_session, sandbox.id)
        db_session.commit()
        # RUNNING is a claim, not a fact: the reaper terminates the pod before
        # it writes SLEEPING, and an evicted pod is never written down at all.
        if get_sandbox_manager().health_check(
            sandbox.id, timeout=HEALTH_PROBE_TIMEOUT_SECONDS
        ):
            return sandbox
        logger.warning(
            "Session %s claims a RUNNING sandbox with no live pod; waking it",
            session_id,
        )

    if session is None:
        raise RuntimeError(f"Build session {session_id} not found")
    user = fetch_user_by_id(db_session, user_id)
    if user is None:
        raise RuntimeError(f"User {user_id} not found")

    logger.info(
        "Interactive turn is waking session %s (session=%s sandbox=%s)",
        session_id,
        session.status.value,
        sandbox.status.value if sandbox else "missing",
    )
    with session_creation_lock(user_id):
        return ensure_session_ready(db_session, get_sandbox_manager(), session, user)


def _drive_interactive_turn(
    *,
    turn_id: UUID,
    session_id: UUID,
    user_id: UUID,
    prompt: str,
    turn_index: int,
    attachments: list[PromptAttachment],
    budget_seconds: int,
    runner_id: str | None,
    reclaimed: bool,
) -> None:
    cache = get_cache_backend()
    with get_session_with_current_tenant() as db_session:
        session_manager = SessionManager(db_session)
        sandbox = _ready_session_runtime(db_session, session_id, user_id)
        db_session.commit()

        if not touch_turn(cache=cache, turn_id=turn_id, runner_id=runner_id):
            logger.info("Interactive turn %s runner ownership lost", turn_id)
            return

        state = BuildStreamingState(turn_index=turn_index)
        deadline = time.monotonic() + budget_seconds
        deadline_exceeded = False

        def interrupt_requested() -> bool:
            nonlocal deadline_exceeded
            if time.monotonic() > deadline:
                deadline_exceeded = True
                return True
            try:
                return is_interrupt_requested(session_id, cache)
            except CACHE_TRANSIENT_ERRORS:
                logger.warning(
                    "[SANDBOX-SERVE] interrupt fence check failed for session %s",
                    session_id,
                    exc_info=True,
                )
                return False

        def persist_turn_error(message: str) -> None:
            """Best-effort user-visible failure row; never blocks finish_turn."""
            try:
                db_session.rollback()
                session_manager.persist_turn_error(
                    session_id, turn_index, f"{message} {_TURN_ERROR_SUFFIX}"
                )
                db_session.commit()
            except Exception:
                logger.exception(
                    "Failed to persist turn error message for turn %s", turn_id
                )

        prompt_slot_cm = session_manager.prompt_slot(
            sandbox.id,
            session_id,
            acquire_timeout=(
                PROMPT_SLOT_WAIT_OUT_ORPHAN_SECONDS
                if reclaimed
                else PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS
            ),
        )
        slot = prompt_slot_cm.__enter__()
        if not slot.acquired:
            # Ownership check first: a stalled runner whose turn was reclaimed
            # also lands here, and the successor IS processing the message —
            # it must not leave a false "wasn't processed" row.
            if touch_turn(cache=cache, turn_id=turn_id, runner_id=runner_id):
                try:
                    session_manager.persist_turn_error(
                        session_id,
                        turn_index,
                        "Another turn was still running for this session, so "
                        "this message wasn't processed. Wait for it to finish, "
                        "then send your message again.",
                    )
                    db_session.commit()
                except Exception:
                    logger.exception(
                        "Failed to persist turn error message for turn %s", turn_id
                    )
            finish_turn(
                cache=cache,
                turn_id=turn_id,
                status=TURN_STATUS_FAILED,
                error_detail="Concurrent turn in flight for build session.",
                runner_id=runner_id,
            )
            prompt_slot_cm.__exit__(None, None, None)
            return

        try:
            # Re-check ownership after the (possibly long) slot wait: a reclaim acquire
            # can block past RUNNER_STALE_AFTER_SECONDS, letting another
            # runner steal the turn — it must not reach the prompt POST.
            if not touch_turn(cache=cache, turn_id=turn_id, runner_id=runner_id):
                logger.info("Interactive turn %s runner ownership lost", turn_id)
                return

            session = session_manager.get_session(session_id, user_id)
            user = fetch_user_by_id(db_session, user_id)
            if session is None or user is None:
                raise RuntimeError("Craft session owner or session no longer exists")
            session_manager.reconcile_session_llm_config(sandbox, session, user)
            db_session.commit()

            # Only while holding the slot — a racing loser must not overwrite
            # the live turn's stamp. Continuations don't restamp.
            session_manager.stamp_turn_deadline(
                sandbox.id,
                session_id,
                soft_budget_seconds=min(
                    INTERACTIVE_TURN_SOFT_BUDGET_SECONDS, budget_seconds
                ),
                hard_cap_seconds=budget_seconds,
            )

            if interrupt_requested():
                session_manager.finalize_persist(session_id, state)
                db_session.commit()
                finish_turn(
                    cache=cache,
                    turn_id=turn_id,
                    status=TURN_STATUS_CANCELLED,
                    runner_id=runner_id,
                )
                return

            def drive_one_prompt(
                current_prompt: str,
                prompt_attachments: list[PromptAttachment],
                *,
                can_continue: bool,
            ) -> _PromptResult:
                """Stream one opencode prompt to completion, timeout, or a
                turn-ending failure. On the recoverable inactivity timeout it
                returns TIMED_OUT (only while ``can_continue``); failures finish
                the turn here and return TERMINATED so the caller just returns."""
                nonlocal deadline_exceeded
                ownership_lost = False
                final_event_seen = False
                cancelled_event_seen = False
                timed_out = False

                event_stream = session_manager.yield_sandbox_events(
                    sandbox.id,
                    session_id,
                    current_prompt,
                    attachments=prompt_attachments,
                    should_interrupt=interrupt_requested,
                    should_abort_on_teardown=lambda: not ownership_lost,
                )

                for sandbox_event in event_stream:
                    if time.monotonic() > deadline:
                        deadline_exceeded = True
                    if deadline_exceeded:
                        continue

                    if not touch_turn(
                        cache=cache, turn_id=turn_id, runner_id=runner_id
                    ):
                        logger.info(
                            "Interactive turn %s runner ownership lost", turn_id
                        )
                        ownership_lost = True
                        return _PromptResult(_PromptOutcome.TERMINATED)
                    slot.extend()
                    if slot.lost:
                        ownership_lost = True
                        session_manager.finalize_persist(session_id, state)
                        db_session.commit()
                        persist_turn_error(
                            "This turn was interrupted and could not finish."
                        )
                        finish_turn(
                            cache=cache,
                            turn_id=turn_id,
                            status=TURN_STATUS_FAILED,
                            error_detail="Prompt slot lease lost mid-turn.",
                            runner_id=runner_id,
                        )
                        return _PromptResult(_PromptOutcome.TERMINATED)
                    if isinstance(sandbox_event, SSEKeepalive):
                        continue

                    # The transport already aborted the timed-out step and ends the
                    # stream after this event; drain it (don't return early, which
                    # would GeneratorExit and re-abort) and let the caller re-prompt.
                    if isinstance(sandbox_event, ActivityTimeoutError) and can_continue:
                        timed_out = True
                        continue

                    session_manager.persist_sandbox_event(
                        session_id, state, sandbox_event
                    )
                    db_session.commit()

                    if isinstance(sandbox_event, SandboxError):
                        session_manager.finalize_persist(session_id, state)
                        db_session.commit()
                        persist_turn_error(sandbox_event.message)
                        finish_turn(
                            cache=cache,
                            turn_id=turn_id,
                            status=TURN_STATUS_FAILED,
                            error_detail=sandbox_event.message,
                            runner_id=runner_id,
                        )
                        return _PromptResult(_PromptOutcome.TERMINATED)

                    if isinstance(sandbox_event, PromptResponse):
                        final_event_seen = True
                        cancelled_event_seen = (
                            getattr(  # ods: ignore[getattr]
                                sandbox_event, "stop_reason", None
                            )
                            == "cancelled"
                        )

                if timed_out:
                    return _PromptResult(_PromptOutcome.TIMED_OUT)
                return _PromptResult(
                    _PromptOutcome.COMPLETED,
                    final_event_seen=final_event_seen,
                    cancelled=cancelled_event_seen,
                )

            result = _PromptResult(_PromptOutcome.COMPLETED)
            current_prompt = prompt
            for attempt in range(MAX_TIMEOUT_CONTINUATIONS + 1):
                result = drive_one_prompt(
                    current_prompt,
                    attachments if attempt == 0 else [],
                    can_continue=attempt < MAX_TIMEOUT_CONTINUATIONS,
                )
                if result.outcome is not _PromptOutcome.TIMED_OUT:
                    break
                # Flush the aborted step's partial output as its own message so it
                # can't merge with the continuation, then steer the agent.
                session_manager.finalize_persist(session_id, state)
                db_session.commit()
                logger.info(
                    "Interactive turn %s step timed out; re-prompting (%s/%s)",
                    turn_id,
                    attempt + 1,
                    MAX_TIMEOUT_CONTINUATIONS,
                )
                current_prompt = _TOOL_TIMEOUT_CONTINUATION_PROMPT

            if result.outcome is _PromptOutcome.TERMINATED:
                return

            session_manager.finalize_persist(session_id, state)
            db_session.commit()

            if deadline_exceeded:
                persist_turn_error(
                    "This turn was stopped after reaching its "
                    f"{max(1, round(budget_seconds / 60))}-minute time limit."
                )
                finish_turn(
                    cache=cache,
                    turn_id=turn_id,
                    status=TURN_STATUS_FAILED,
                    error_detail=f"hard time cap exceeded ({budget_seconds}s)",
                    runner_id=runner_id,
                )
                return

            if not result.final_event_seen:
                persist_turn_error(
                    "This turn ended before the agent returned a final response."
                )
                finish_turn(
                    cache=cache,
                    turn_id=turn_id,
                    status=TURN_STATUS_FAILED,
                    error_detail="Turn ended before opencode returned a final response.",
                    runner_id=runner_id,
                )
                return

            if result.cancelled:
                finish_turn(
                    cache=cache,
                    turn_id=turn_id,
                    status=TURN_STATUS_CANCELLED,
                    runner_id=runner_id,
                )
                return

            finish_turn(
                cache=cache,
                turn_id=turn_id,
                status=TURN_STATUS_SUCCEEDED,
                runner_id=runner_id,
            )
        except Exception as exc:
            db_session.rollback()
            logger.exception("Interactive turn %s failed", turn_id)
            try:
                session_manager.finalize_persist(session_id, state)
                db_session.commit()
            except Exception:
                logger.exception("Failed to finalize persistence for turn %s", turn_id)
            persist_turn_error("This turn failed unexpectedly.")
            finish_turn(
                cache=cache,
                turn_id=turn_id,
                status=TURN_STATUS_FAILED,
                error_detail=f"{type(exc).__name__}: {str(exc)[:950]}",
                runner_id=runner_id,
            )
        finally:
            # True on every exit where this runner still owns the turn (normal
            # end, owned failure, cancel, exception); False once a successor
            # owns it (reclaim / slot-lost with a new turn). A successor sets
            # the active-turn pointer at creation, before it ever stamps, so
            # this guard clears our deadline exactly when no other turn's stamp
            # can be clobbered.
            try:
                still_owns_turn = _can_clear_interrupt_fence(
                    cache=cache,
                    turn_id=turn_id,
                    session_id=session_id,
                    user_id=user_id,
                    runner_id=runner_id,
                )
            except CACHE_TRANSIENT_ERRORS:
                logger.warning(
                    "[SANDBOX-SERVE] interrupt-fence ownership check failed for session %s",
                    session_id,
                    exc_info=True,
                )
                still_owns_turn = False
            if still_owns_turn:
                try:
                    clear_interrupt(session_id, cache)
                except CACHE_TRANSIENT_ERRORS:
                    logger.warning(
                        "[SANDBOX-SERVE] failed to clear interrupt fence for session %s",
                        session_id,
                        exc_info=True,
                    )
                session_manager.clear_turn_deadline(sandbox.id, session_id)
            prompt_slot_cm.__exit__(None, None, None)
