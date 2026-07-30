"""Is a sandbox committed to work right now?

A sandbox is shared by all of a user's sessions, so anything that disturbs one
— recycling it onto a new image, reaping it, restarting a container under it —
has to know whether work is queued or in flight. Heartbeat cannot answer that:
an open tab beats identically whether the agent is mid-turn or the user is
reading the last answer.

The answer comes from two places, because work reaches a sandbox by two routes
that share no state:

- interactive chats, tracked in the turn cache (``interactive_turns.state``),
  where a *queued* turn counts — a message submitted a moment ago is work the
  sandbox owes even though nothing has started;
- scheduled runs, tracked in Postgres, which never register an interactive turn
  and are therefore invisible to the cache.

Claims are returned rather than a bool. A drain that has been stuck for an hour
is a support question, and "blocked by a scheduled run awaiting approval" answers
it while ``False`` does not.

Not covered here: a prompt already streaming to opencode. That is what
``prompt_slot`` serialises, and a caller about to mutate a sandbox should acquire
those slots rather than poll them — holding the same lock the chat path takes is
both the check and the barrier, with no window in between. This module answers
the cheaper question that comes first.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.models import Sandbox
from onyx.db.scheduled_task import get_unfinished_run_for_user
from onyx.server.features.build.db.build_session import (
    get_active_session_ids_for_user,
)
from onyx.server.features.build.interactive_turns.state import get_active_turn


class SandboxBusyKind(str, Enum):
    """What kind of work holds the sandbox."""

    INTERACTIVE_TURN = "interactive_turn"
    SCHEDULED_RUN = "scheduled_run"


class SandboxBusyClaim(BaseModel):
    """Work that makes a sandbox unsafe to disturb, and enough detail to say so
    in a log line or a support answer."""

    model_config = ConfigDict(frozen=True)

    kind: SandboxBusyKind
    detail: str


def sandbox_busy_claim(
    db_session: DBSession,
    sandbox: Sandbox,
    *,
    cache: CacheBackend | None = None,
) -> SandboxBusyClaim | None:
    """The first claim found on this sandbox, or None if it is free.

    Cheapest probe first, and it stops at the first hit: callers only ever need
    to know *that* the sandbox is busy plus one reason to report.
    """
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
    """A queued or running turn on any of the user's sessions.

    Terminating a pod mid-turn drops the turn with no recovery, and killing one
    with a message queued loses a request the user has already been told was
    accepted.
    """
    for session_id in get_active_session_ids_for_user(sandbox.user_id, db_session):
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
    """A scheduled run that has not finished.

    The scheduled-task executor drives the sandbox without registering an
    interactive turn, so nothing above sees it. A run in ``AWAITING_APPROVAL``
    counts too — it is waiting on a person and will resume in this sandbox.
    """
    run = get_unfinished_run_for_user(db_session=db_session, user_id=sandbox.user_id)
    if run is None:
        return None
    return SandboxBusyClaim(
        kind=SandboxBusyKind.SCHEDULED_RUN,
        detail=f"run {run.id} is {run.status.value}",
    )
