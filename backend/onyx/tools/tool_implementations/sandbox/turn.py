"""The sandbox that the sandbox tools of one chat session share during a run."""

import threading
from collections.abc import Iterable, Sequence
from uuid import UUID

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import User
from onyx.db.sandbox import get_or_create_sandbox
from onyx.db.skill import list_chat_skills
from onyx.server.features.build.sandbox.harness_base import HarnessSandbox
from onyx.server.features.build.sandbox.models import HarnessSandboxRef, SkillsBundle
from onyx.skills.models import ChatSkill
from onyx.tools.tool_implementations.sandbox.file_copies import TurnFileCopies
from onyx.tools.tool_implementations.sandbox.models import VmChatFile
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
        self._skills_lock = threading.Lock()
        self._skills_loaded = False
        self._skills_bundle: SkillsBundle | None = None
        self.file_copies: TurnFileCopies | None = None
        # Custom skills the model read or the user picked, by name; resolved
        # to the user's current version once per turn.
        self._wanted: set[str] = set()
        self._resolved: set[str] = set()
        self._custom: dict[str, ChatSkill] = {}
        self._custom_bundles: dict[str, SkillsBundle | None] = {}

    def want_skills(self, names: Iterable[str]) -> None:
        """Copy these custom skills to the VM before the next call."""
        # Not the skills lock: a step does not wait for a copy in progress.
        with self._lock:
            self._wanted.update(names)

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
        self._sync_skills(ref)
        return ref

    def _sync_skills(self, ref: HarnessSandboxRef) -> None:
        # Deferred: the skills push stack loads only when a tool runs.
        from onyx.skills.push import build_chat_built_ins_bundle

        with self._skills_lock:
            try:
                if not self._skills_loaded:
                    with get_session_with_tenant(
                        tenant_id=self._tenant_id
                    ) as db_session:
                        self._skills_bundle = build_chat_built_ins_bundle(db_session)
                    self._skills_loaded = True
                # Every call: a VM that replaced a stopped one mid-turn needs
                # the push too, and an unchanged instance is skipped.
                if self._skills_bundle is not None:
                    self.sandbox.sync_skills(ref, self._skills_bundle)
            except Exception:
                logger.exception(
                    "sandbox_skills_sync_failed sandbox=%s session=%s",
                    ref.sandbox_id,
                    ref.session_id,
                )
            try:
                self._install_custom_skills(ref)
            except Exception:
                logger.exception(
                    "sandbox_skills_install_failed sandbox=%s session=%s",
                    ref.sandbox_id,
                    ref.session_id,
                )

    def _install_custom_skills(self, ref: HarnessSandboxRef) -> None:
        # Deferred: the skills push stack loads only when a tool runs.
        from onyx.skills.push import build_chat_custom_skill_bundle

        with self._lock:
            unresolved = self._wanted - self._resolved
        if unresolved:
            with get_session_with_tenant(tenant_id=self._tenant_id) as db_session:
                skills = list_chat_skills(db_session, self._user, built_ins=True)
            # The first skill of a name, as skills_read picks. A built-in is on
            # the skills drive already.
            for name in unresolved:
                skill = next((s for s in skills if s.name == name), None)
                if skill is not None and skill.built_in_skill_id is None:
                    self._custom[name] = skill
            self._resolved |= unresolved
        if not self._custom:
            return

        def load(name: str) -> SkillsBundle | None:
            if name not in self._custom_bundles:
                with get_session_with_tenant(tenant_id=self._tenant_id) as db_session:
                    self._custom_bundles[name] = build_chat_custom_skill_bundle(
                        self._custom[name], self._user, db_session
                    )
            return self._custom_bundles[name]

        self.sandbox.install_skills(
            ref,
            {
                name: f"{skill.version_id}:{skill.path}"
                for name, skill in self._custom.items()
            },
            load,
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
