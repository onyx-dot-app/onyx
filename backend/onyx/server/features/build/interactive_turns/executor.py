"""Background executor for interactive Craft turns."""

from __future__ import annotations

import threading
import time
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.features.build.db.build_session import update_session_activity
from onyx.server.features.build.interactive_turns.state import claim_turn_for_runner
from onyx.server.features.build.interactive_turns.state import finish_turn
from onyx.server.features.build.interactive_turns.state import get_active_turn
from onyx.server.features.build.interactive_turns.state import InteractiveTurn
from onyx.server.features.build.interactive_turns.state import touch_turn
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_CANCELLED
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_FAILED
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_SUCCEEDED
from onyx.server.features.build.sandbox.event_schema import Error as SandboxError
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from onyx.server.features.build.session.interrupt_signal import clear_interrupt
from onyx.server.features.build.session.interrupt_signal import is_interrupt_requested
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.streaming import BuildStreamingState
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

DEFAULT_INTERACTIVE_TURN_BUDGET_SECONDS = 30 * 60


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
    budget_seconds: int = DEFAULT_INTERACTIVE_TURN_BUDGET_SECONDS,
) -> None:
    """Execute a turn that this runner has already claimed in CacheBackend."""
    cache = get_cache_backend()
    runner_id = turn.runner_id
    try:
        _drive_interactive_turn(
            turn_id=turn.turn_id,
            session_id=turn.session_id,
            user_id=turn.user_id,
            prompt=turn.prompt,
            turn_index=turn.turn_index,
            budget_seconds=budget_seconds,
            runner_id=runner_id,
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


def _drive_interactive_turn(
    *,
    turn_id: UUID,
    session_id: UUID,
    user_id: UUID,
    prompt: str,
    turn_index: int,
    budget_seconds: int,
    runner_id: str | None,
) -> None:
    cache = get_cache_backend()
    with get_session_with_current_tenant() as db_session:
        session_manager = SessionManager(db_session)
        sandbox = session_manager.ensure_sandbox_running(user_id)
        db_session.commit()

        if not touch_turn(cache=cache, turn_id=turn_id, runner_id=runner_id):
            logger.info("Interactive turn %s runner ownership lost", turn_id)
            return

        state = BuildStreamingState(turn_index=turn_index)
        deadline = time.monotonic() + budget_seconds
        deadline_exceeded = False
        final_event_seen = False
        cancelled_event_seen = False

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

        prompt_slot_cm = session_manager.prompt_slot(sandbox.id, session_id)
        if not prompt_slot_cm.__enter__():
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
            update_session_activity(session_id, db_session)

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

            event_stream = session_manager.yield_sandbox_events(
                sandbox.id,
                session_id,
                prompt,
                should_interrupt=interrupt_requested,
            )

            for sandbox_event in event_stream:
                if time.monotonic() > deadline:
                    deadline_exceeded = True
                if deadline_exceeded:
                    continue

                if not touch_turn(cache=cache, turn_id=turn_id, runner_id=runner_id):
                    logger.info("Interactive turn %s runner ownership lost", turn_id)
                    return
                if isinstance(sandbox_event, SSEKeepalive):
                    continue
                session_manager.persist_sandbox_event(session_id, state, sandbox_event)
                db_session.commit()

                if isinstance(sandbox_event, SandboxError):
                    session_manager.finalize_persist(session_id, state)
                    db_session.commit()
                    finish_turn(
                        cache=cache,
                        turn_id=turn_id,
                        status=TURN_STATUS_FAILED,
                        error_detail=sandbox_event.message,
                        runner_id=runner_id,
                    )
                    return

                if isinstance(sandbox_event, PromptResponse):
                    final_event_seen = True
                    cancelled_event_seen = (
                        getattr(sandbox_event, "stop_reason", None) == "cancelled"
                    )

            session_manager.finalize_persist(session_id, state)
            db_session.commit()

            if deadline_exceeded:
                finish_turn(
                    cache=cache,
                    turn_id=turn_id,
                    status=TURN_STATUS_FAILED,
                    error_detail=f"budget exceeded ({budget_seconds}s)",
                    runner_id=runner_id,
                )
                return

            if not final_event_seen:
                finish_turn(
                    cache=cache,
                    turn_id=turn_id,
                    status=TURN_STATUS_FAILED,
                    error_detail="Turn ended before opencode returned a final response.",
                    runner_id=runner_id,
                )
                return

            if cancelled_event_seen:
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
            finish_turn(
                cache=cache,
                turn_id=turn_id,
                status=TURN_STATUS_FAILED,
                error_detail=f"{type(exc).__name__}: {str(exc)[:950]}",
                runner_id=runner_id,
            )
        finally:
            try:
                if _can_clear_interrupt_fence(
                    cache=cache,
                    turn_id=turn_id,
                    session_id=session_id,
                    user_id=user_id,
                    runner_id=runner_id,
                ):
                    clear_interrupt(session_id, cache)
            except CACHE_TRANSIENT_ERRORS:
                logger.warning(
                    "[SANDBOX-SERVE] failed to clear interrupt fence for session %s",
                    session_id,
                    exc_info=True,
                )
            prompt_slot_cm.__exit__(None, None, None)
