"""The sandbox that the sandbox tools of one chat session share during a run."""

import threading
from collections.abc import Sequence
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.sandbox import get_or_create_sandbox
from onyx.server.features.build.sandbox.file_copy_state import (
    COPY_STATE_SECONDS,
    copy_generation_key,
)
from onyx.server.features.build.sandbox.harness_base import HarnessSandbox
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.tools.tool_implementations.sandbox.file_copies import (
    COPY_CACHE_SECONDS,
    CopyTarget,
    TurnFileCopies,
    TurnSearchFiles,
)
from onyx.tools.tool_implementations.sandbox.models import VmChatFile
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SandboxTurn:
    """The user's sandbox, seen from one chat session, for the tools built
    together for one model response. The runs of the response (the root run
    and its subagent runs) share it.

    The first call resolves the user's Sandbox row, unless a search's copy
    did. Each call renews the sandbox's turn mark before it runs, which keeps
    the sandbox busy. After the first call, each release of the root run (it
    finishes or suspends, and its work and the work of its foreground
    children drain) ends the turn: `end` is the root agent's on_drained hook
    (`chat/execution.py:create_chat_agent`). Subagent runs never end it, since
    the root can be mid-call when they release; a background subagent that
    outlives the root leaves its renewed mark to expire.

    `vm_chat_files` are the chat's files in the VM. In a turn that copies
    them (`copy_vm_chat_files`), the first call starts `file_copies`, their
    background copy; the root chat agent adds its status line to sandbox and
    code mode results (`chat/agent.py`). `search_files` copies the files of
    the turn's search results (`file_copies.py`). Creating the turn takes the
    chat's next copy generation, which both copies use.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        user_id: UUID,
        chat_session_id: UUID,
        vm_chat_files: Sequence[VmChatFile],
        copy_vm_chat_files: bool,
    ) -> None:
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._chat_session_id = chat_session_id
        self.vm_chat_files = vm_chat_files
        self._copy_vm_chat_files = copy_vm_chat_files
        self._lock = threading.Lock()
        # A call ran.
        self._called = False
        # The user's sandbox, resolved once, by a call or a copy.
        self._ref: HarnessSandboxRef | None = None
        # The turn's copy generation (the Generations rule in
        # file_copies.py). None: the cache failed, and the turn copies nothing.
        self._generation: int | None = None
        try:
            self._generation = get_cache_backend(
                tenant_id=tenant_id, operation_timeout_s=COPY_CACHE_SECONDS
            ).incr(copy_generation_key(chat_session_id), ex=COPY_STATE_SECONDS)
        except Exception:
            logger.exception(
                "sandbox_copy_generation_failed session=%s", chat_session_id
            )
        self.file_copies: TurnFileCopies | None = None
        self.search_files = TurnSearchFiles(self.copy_target, user_id)

    @property
    def sandbox(self) -> HarnessSandbox:
        # Deferred: the sandbox client stack loads only when a tool runs.
        from onyx.server.features.build.sandbox.harness_factory import (
            get_harness_sandbox,
        )

        return get_harness_sandbox()

    def _resolve(self) -> HarnessSandboxRef:
        """The user's sandbox for this chat; the first use reads the row."""
        with self._lock:
            ref = self._ref
        if ref is not None:
            return ref
        # Outside the lock: concurrent first uses get the same row.
        with get_session_with_tenant(tenant_id=self._tenant_id) as db_session:
            sandbox_id = get_or_create_sandbox(db_session, self._user_id).id
        with self._lock:
            if self._ref is None:
                self._ref = HarnessSandboxRef(
                    tenant_id=self._tenant_id,
                    sandbox_id=sandbox_id,
                    session_id=self._chat_session_id,
                )
            return self._ref

    def copy_target(self) -> CopyTarget:
        """Where the turn's copies of either kind go, with the turn's copy
        generation."""
        if self._generation is None:
            raise RuntimeError("The turn has no copy generation")
        return CopyTarget(self._resolve(), self.sandbox, self._generation)

    def start_call(self) -> HarnessSandboxRef:
        """The sandbox reference for one call, with the turn mark renewed.
        The first call starts the copy of the chat's files."""
        ref = self._resolve()
        with self._lock:
            first = not self._called
            self._called = True
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
        if first and self._copy_vm_chat_files:
            # A copy that fails to start leaves the files to the next turn.
            try:
                target = self.copy_target()
                self.file_copies = TurnFileCopies(
                    target.ref,
                    target.sandbox,
                    self.vm_chat_files,
                    generation=target.generation,
                )
            except Exception:
                logger.exception(
                    "sandbox_file_copies_start_failed sandbox=%s session=%s",
                    ref.sandbox_id,
                    ref.session_id,
                )
        return ref

    def end(self) -> None:
        """End the turn if a call started one. Never raises."""
        with self._lock:
            ref = self._ref if self._called else None
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

    @property
    def user_id(self) -> UUID:
        """The user whose sandbox it is; reading it never starts a call."""
        return self._user_id

    @property
    def chat_session_id(self) -> UUID:
        """The chat whose session directory the calls use; reading it never
        starts a call."""
        return self._chat_session_id
