"""Is a sandbox committed to work right now?

Work reaches a shared sandbox by two routes that share no state: interactive
chats in the turn cache, and scheduled runs in Postgres. The scheduled executor
registers no interactive turn, so a turn-only check is blind to it.

Claims carry a reason rather than a bool: a recycle blocked for an hour is a
support question, and "blocked by a scheduled run awaiting approval" answers it.

A prompt already streaming is out of scope — ``prompt_slot`` serialises those, so
a caller about to disturb a sandbox should acquire them rather than poll.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.models import Sandbox
from onyx.db.scheduled_task import get_unfinished_run_for_user
from onyx.server.features.build.db.build_session import (
    get_live_session_ids_for_user,
)
from onyx.server.features.build.interactive_turns.state import get_active_turn


class SandboxBusyKind(str, Enum):
    """What kind of work holds the sandbox."""

    INTERACTIVE_TURN = "interactive_turn"
    SCHEDULED_RUN = "scheduled_run"


class SandboxBusyClaim(BaseModel):
    """Work that makes a sandbox unsafe to disturb, and why."""

    model_config = ConfigDict(frozen=True)

    kind: SandboxBusyKind
    detail: str


def sandbox_busy_claim(
    db_session: DBSession,
    sandbox: Sandbox,
    *,
    cache: CacheBackend | None = None,
) -> SandboxBusyClaim | None:
    """The first claim found on this sandbox, cheapest probe first, or None."""
    cache = cache or get_cache_backend()
    for probe in (_interactive_turn_claim, _scheduled_run_claim):
        claim = probe(db_session, sandbox, cache)
        if claim is not None:
            return claim
    return None


def _interactive_turn_claim(
    db_session: DBSession,
    sandbox: Sandbox,
    cache: CacheBackend,
) -> SandboxBusyClaim | None:
    """A queued or running turn on any of the user's live sessions.

    Queued counts: the user has already been told the message was accepted.
    """
    for session_id in get_live_session_ids_for_user(sandbox.user_id, db_session):
        turn = get_active_turn(
            cache=cache,
            session_id=session_id,
            user_id=sandbox.user_id,
        )
        if turn is not None:
            return SandboxBusyClaim(
                kind=SandboxBusyKind.INTERACTIVE_TURN,
                detail=f"session {session_id} turn {turn.turn_id} is {turn.status}",
            )
    return None


def _scheduled_run_claim(
    db_session: DBSession,
    sandbox: Sandbox,
    cache: CacheBackend,  # noqa: ARG001
) -> SandboxBusyClaim | None:
    """A scheduled run that has not finished, including one awaiting approval —
    that one waits on a person and will resume in this sandbox."""
    run = get_unfinished_run_for_user(db_session=db_session, user_id=sandbox.user_id)
    if run is None:
        return None
    return SandboxBusyClaim(
        kind=SandboxBusyKind.SCHEDULED_RUN,
        detail=f"run {run.id} is {run.status.value}",
    )
