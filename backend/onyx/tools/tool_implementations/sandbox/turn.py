"""The sandbox that the sandbox tools of one chat session share during a run."""

import threading
from collections.abc import Sequence
from uuid import UUID

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import User
from onyx.db.sandbox import get_or_create_sandbox
from onyx.db.skill import list_chat_skills
from onyx.server.features.build.sandbox.harness_base import HarnessSandbox
from onyx.server.features.build.sandbox.models import (
    FileSet,
    HarnessSandboxRef,
    chat_skill_folder,
)
from onyx.tools.tool_implementations.sandbox.file_copies import TurnFileCopies
from onyx.tools.tool_implementations.sandbox.models import VmChatFile
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SkillLoadError(Exception):
    """A skill that load_skill cannot copy: the user has no skill of that
    name, or its files cannot be read."""


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

    `vm_chat_files` are the chat's files in the VM. In a turn that copies
    them (`copy_vm_chat_files`), the first call starts `file_copies`, their
    background copy; the root chat agent adds its status line to sandbox and
    code mode results (`chat/agent.py`).
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        user: User,
        chat_session_id: UUID,
        vm_chat_files: Sequence[VmChatFile],
        copy_vm_chat_files: bool,
    ) -> None:
        self._tenant_id = tenant_id
        self._user = user
        self._chat_session_id = chat_session_id
        self.vm_chat_files = vm_chat_files
        self._copy_vm_chat_files = copy_vm_chat_files
        self._lock = threading.Lock()
        self._ref: HarnessSandboxRef | None = None
        self.file_copies: TurnFileCopies | None = None

    @property
    def sandbox(self) -> HarnessSandbox:
        # Deferred: the sandbox client stack loads only when a tool runs.
        from onyx.server.features.build.sandbox.harness_factory import (
            get_harness_sandbox,
        )

        return get_harness_sandbox()

    def start_call(self) -> HarnessSandboxRef:
        """The sandbox reference for one call, with the turn mark renewed.
        The first call starts the copy of the chat's files."""
        with self._lock:
            ref = self._ref
        first = False
        if ref is None:
            # Outside the lock: concurrent first calls get the same row.
            with get_session_with_tenant(tenant_id=self._tenant_id) as db_session:
                sandbox_id = get_or_create_sandbox(db_session, self._user.id).id
            with self._lock:
                if self._ref is None:
                    self._ref = HarnessSandboxRef(
                        tenant_id=self._tenant_id,
                        sandbox_id=sandbox_id,
                        session_id=self._chat_session_id,
                    )
                    first = True
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
        if first and self._copy_vm_chat_files:
            # A copy that fails to start leaves the files to the next turn.
            try:
                self.file_copies = TurnFileCopies(ref, self.sandbox, self.vm_chat_files)
            except Exception:
                logger.exception(
                    "sandbox_file_copies_start_failed sandbox=%s session=%s",
                    ref.sandbox_id,
                    ref.session_id,
                )
        return ref

    def load_skill(self, ref: HarnessSandboxRef, name: str) -> str:
        """Copy the skill named `name`, at the version the user runs now,
        into its read-only VM folder. Returns the folder. Raises SkillLoadError for an unknown or unreadable skill."""
        from onyx.skills.push import (
            build_chat_built_in_skill_files,
            build_chat_custom_skill_files,
            chat_skill_version,
        )

        with get_session_with_tenant(tenant_id=self._tenant_id) as db_session:
            skill = next(
                (
                    skill
                    for skill in list_chat_skills(
                        db_session, self._user, built_ins=True
                    )
                    if skill.name == name
                ),
                None,
            )
        if skill is None:
            raise SkillLoadError(f"No skill is named '{name}'.")

        if skill.built_in_skill_id is not None:
            files: FileSet | None = build_chat_built_in_skill_files(skill)
        else:
            with get_session_with_tenant(tenant_id=self._tenant_id) as db_session:
                files = build_chat_custom_skill_files(skill, self._user, db_session)
        if files is None:
            raise SkillLoadError(f"The files of skill '{name}' cannot be read now.")
        self.sandbox.install_skill(ref, name, chat_skill_version(skill), files)
        return chat_skill_folder(name)

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
