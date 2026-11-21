"""The sandbox that the sandbox tools of one chat session share during a run."""

import threading
from uuid import UUID

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.sandbox import get_or_create_sandbox
from onyx.db.users import fetch_user_by_id
from onyx.server.features.build.sandbox.harness_base import HarnessSandbox
from onyx.server.features.build.sandbox.models import FileSet, HarnessSandboxRef
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SandboxTurn:
    """The user's sandbox, seen from one chat session, for the tools built
    together for one model response. The runs of the response (the root run
    and its subagent runs) share it.

    The first call resolves the user's Sandbox row, so a resolved row means
    that a call ran. Each call renews the sandbox's turn mark before it runs,
    which keeps the sandbox busy. After the first call, each release of the
    root run (it finishes or suspends, and its work and the work of its
    foreground children drain) ends the turn: `end` is the root agent's
    on_drained hook (`chat/execution.py:create_chat_agent`). Subagent runs never end it,
    since the root can be mid-call when they release; a background subagent
    that outlives the root leaves its renewed mark to expire.
    """

    def __init__(self, *, tenant_id: str, user_id: UUID, chat_session_id: UUID) -> None:
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._chat_session_id = chat_session_id
        self._lock = threading.Lock()
        self._ref: HarnessSandboxRef | None = None
        self._skills_lock = threading.Lock()
        self._skills_files: FileSet | None = None

    @property
    def sandbox(self) -> HarnessSandbox:
        # Deferred: the sandbox client stack loads only when a tool runs.
        from onyx.server.features.build.sandbox.harness_factory import (
            get_harness_sandbox,
        )

        return get_harness_sandbox()

    def start_call(self) -> HarnessSandboxRef:
        """The sandbox reference for one call, with the turn mark renewed."""
        with self._lock:
            ref = self._ref
        if ref is None:
            # Outside the lock: concurrent first calls get the same row.
            with get_session_with_tenant(tenant_id=self._tenant_id) as db_session:
                sandbox_id = get_or_create_sandbox(db_session, self._user_id).id
            with self._lock:
                if self._ref is None:
                    self._ref = HarnessSandboxRef(
                        tenant_id=self._tenant_id,
                        sandbox_id=sandbox_id,
                        session_id=self._chat_session_id,
                    )
                ref = self._ref
        # The mark expires on its own, so a failed renewal only lets a
        # turn-end save run sooner; the call still runs.
        try:
            self.sandbox.begin_turn(ref)
        except Exception:
            logger.exception(
                "sandbox_turn_renew_failed sandbox=%s session=%s",
                ref.sandbox_id,
                ref.session_id,
            )
        self._sync_skills(ref)
        return ref

    def _sync_skills(self, ref: HarnessSandboxRef) -> None:
        # Deferred: the skills push stack loads only when a tool runs.
        from onyx.skills.push import build_chat_built_in_files

        with self._skills_lock:
            try:
                if self._skills_files is None:
                    with get_session_with_tenant(
                        tenant_id=self._tenant_id
                    ) as db_session:
                        user = fetch_user_by_id(db_session, self._user_id)
                        self._skills_files = (
                            build_chat_built_in_files(user, db_session) if user else {}
                        )
                # Every call: a VM that replaced a stopped one mid-turn needs
                # the push too, and an unchanged instance is skipped.
                if self._skills_files:
                    self.sandbox.sync_skills(ref, self._skills_files)
            except Exception:
                logger.exception(
                    "sandbox_skills_sync_failed sandbox=%s session=%s",
                    ref.sandbox_id,
                    ref.session_id,
                )

    def end(self) -> None:
        """End the turn if a call started one. Never raises."""
        with self._lock:
            ref = self._ref
        if ref is None:
            return
        # The turn mark expires on its own, so a failure only delays the
        # turn-end save.
        try:
            self.sandbox.end_turn(ref)
        except Exception:
            logger.exception(
                "sandbox_turn_end_failed sandbox=%s session=%s",
                ref.sandbox_id,
                ref.session_id,
            )
