"""Public interface for session operations.

SessionManager is the main entry point for build session lifecycle management.
It orchestrates session CRUD, message handling, artifact management, and file system access.
"""

import contextlib
import hashlib
import io
import json
import mimetypes
import threading
import uuid
import zipfile
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session as DBSession

from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import MessageType
from onyx.db.enums import BuildSessionStatus, SandboxStatus, SessionOrigin
from onyx.db.external_app import get_connectable_apps_for_user
from onyx.db.llm import (
    fetch_all_accessible_llm_providers,
    fetch_default_craft_model,
    fetch_default_llm_model,
)
from onyx.db.models import BuildMessage, BuildSession, Sandbox, User
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import (
    MAX_TOTAL_UPLOAD_SIZE_BYTES,
    MAX_UPLOAD_FILES_PER_SESSION,
)
from onyx.server.features.build.db.build_session import (
    create_build_session__no_commit,
    create_message,
    delete_build_session__no_commit,
    finalize_session_initialization__no_commit,
    get_build_session,
    get_empty_session_for_user,
    get_session_messages,
    get_user_build_sessions,
    mark_session_initializing__no_commit,
    reserve_nextjs_port__no_commit,
    session_runtime_stale,
    update_session_activity,
)
from onyx.server.features.build.db.sandbox import (
    get_sandbox_by_user_id,
    get_snapshots_for_session,
    update_sandbox_heartbeat,
)
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.sandbox.models import (
    CraftLLMProviderConfig,
    DirectoryListing,
    FilesystemEntry,
    PromptAttachment,
)
from onyx.server.features.build.sandbox.nextjs_dev import (
    WEBAPP_PACKAGE_JSON_PATH,
)
from onyx.server.features.build.sandbox.serve_transport import PromptSlot
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_connectable_apps_list,
)
from onyx.server.features.build.sandbox.util.mcp_config import (
    resolve_craft_mcp_servers,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_provider_opencode_config,
)
from onyx.server.features.build.session import streaming as _streaming
from onyx.server.features.build.session.errors import (
    StaleProvisioningAttemptError,
    UploadLimitExceededError,
)
from onyx.server.features.build.session.interrupt_signal import request_interrupt
from onyx.server.features.build.session.llm_config import (
    AgentSelection,
    GatewaySelection,
    build_onyx_gateway_config,
    parse_agent_selection,
)
from onyx.server.features.build.session.md_to_docx import markdown_to_docx_bytes
from onyx.server.features.build.session.naming import generate_session_name
from onyx.server.features.build.session.sandbox_lifecycle import (
    ProvisioningPolicy,
    ensure_sandbox_ready,
    sync_managed_content,
)
from onyx.server.features.build.session.streaming import BuildStreamingState
from onyx.server.features.build.timeouts import (
    PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
    PROMPT_SLOT_KEEP_ALIVE_MAX_SECONDS,
    PROVISION_WAIT_SECONDS,
)
from onyx.server.features.build.utils import get_opencode_disabled_tools
from onyx.server.metrics.craft_sandbox import SandboxReadyOutcome
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_DISPOSE_PENDING_TTL_SECONDS = 24 * 3600


def _dispose_pending_key(session_id: UUID) -> str:
    return f"craft:llm_config_dispose_pending:{session_id}"


def mark_opencode_dispose_pending(session_id: UUID) -> None:
    """Claim the dispose owed to a running instance after rewriting its config.

    ``reconcile_session_llm_config`` performs it on the next turn, and needs the
    marker because it short-circuits when the file already matches what it would
    write — which it does after a workspace rebuild.
    """
    get_cache_backend().set(
        _dispose_pending_key(session_id), "1", ex=_DISPOSE_PENDING_TTL_SECONDS
    )


# Webapp-ready probe on the UI-poll hot path; any response (even 404) counts.
_WEBAPP_PROBE_TIMEOUT_SECONDS = 2.0


# Hidden directories/files to filter from listings
HIDDEN_PATTERNS = {
    ".venv",
    ".git",
    ".next",
    "__pycache__",
    "node_modules",
    ".DS_Store",
    "opencode.json",
    ".env",
    ".gitignore",
    "nextjs.log",
    "nextjs.pid",
}

_WEBAPP_DIRECTORY = str(Path(WEBAPP_PACKAGE_JSON_PATH).parent)
_WEBAPP_PACKAGE_FILENAME = Path(WEBAPP_PACKAGE_JSON_PATH).name


def _sanitize_zip_basename(name: str, *, allow_dots: bool) -> str:
    """Replace filesystem-unsafe characters in a zip filename stem. ``allow_dots``
    keeps version-suffixed directory names like ``my.lib`` intact."""
    safe = {"-", "_", "."} if allow_dots else {"-", "_"}
    return "".join(c if c.isalnum() or c in safe else "_" for c in name)


def _is_hidden_workspace_entry(entry: FilesystemEntry) -> bool:
    return entry.name in HIDDEN_PATTERNS or entry.name.startswith(".")


class SessionManager:
    """Public interface for session operations.

    Orchestrates session lifecycle, messaging, artifacts, and file access.
    Uses SandboxManager internally for sandbox-related operations.

    Unlike SandboxManager, this is NOT a singleton - each instance is bound
    to a specific database session for the duration of a request.

    Usage:
        session_manager = SessionManager(db_session)
        sessions = session_manager.list_sessions(user_id)
    """

    def __init__(self, db_session: DBSession) -> None:
        """Initialize the SessionManager with a database session.

        Args:
            db_session: The SQLAlchemy database session to use for all operations
        """
        self._db_session = db_session
        self._sandbox_manager = get_sandbox_manager()

    # =========================================================================
    # LLM Configuration
    # =========================================================================

    def build_llm_configs(
        self,
        user: User,
        selection: AgentSelection | None = None,
    ) -> CraftLLMProviderConfig:
        # Craft outranks chat: an admin can point Craft at a coding model while
        # chat stays on something else.
        configured_default_models = [
            fetch_default_craft_model(self._db_session),
            fetch_default_llm_model(self._db_session),
        ]
        configured_defaults = [
            GatewaySelection(model.llm_provider_id, model.name)
            for model in configured_default_models
            if model is not None
        ]
        gateway_config = build_onyx_gateway_config(
            fetch_all_accessible_llm_providers(self._db_session, user),
            selection,
            configured_defaults,
        )
        if gateway_config is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "No accessible LLM provider with a visible model is configured.",
            )
        return gateway_config

    # =========================================================================
    # Session CRUD Operations
    # =========================================================================

    def list_sessions(
        self,
        user_id: UUID,
    ) -> list[BuildSession]:
        """Get all build sessions for a user.

        Args:
            user_id: The user ID

        Returns:
            List of BuildSession models ordered by most recent first
        """
        return get_user_build_sessions(user_id, self._db_session)

    def _prewarm_opencode_session(
        self, sandbox: Sandbox, session: BuildSession
    ) -> None:
        """Mint and persist the OpenCode session before the first prompt.

        The caller owns the surrounding transaction. This keeps the empty Craft
        session's runtime ID and acknowledged skills generation aligned.
        """
        opencode_session_id = self._sandbox_manager.ensure_opencode_session(
            sandbox_id=sandbox.id,
            session_id=session.id,
            opencode_session_id=session.opencode_session_id,
        )
        if opencode_session_id is None:
            raise RuntimeError(
                f"Failed to prewarm opencode session for build session {session.id}"
            )
        if session.opencode_session_id != opencode_session_id:
            logger.info(
                "Prewarmed opencode session %s for build session %s",
                opencode_session_id,
                session.id,
            )
            session.opencode_session_id = opencode_session_id
            session.skills_hash = sandbox.skills_hash
            session.mcp_config_hash = sandbox.mcp_config_hash
            self._db_session.flush()

    def session_llm_config(
        self, session: BuildSession, user: User
    ) -> CraftLLMProviderConfig:
        """Resolve the LLM config a session's opencode.json should carry from
        its persisted provider/model selection (falling back to the gateway
        default when the selection is unset or no longer accessible)."""
        selection = parse_agent_selection(session.agent_provider, session.agent_model)
        return self.build_llm_configs(user, selection)

    def reconcile_session_llm_config(
        self,
        sandbox: Sandbox,
        session: BuildSession,
        user: User,
    ) -> None:
        llm_config = self.session_llm_config(session, user)
        mcp_servers = resolve_craft_mcp_servers(self._db_session, user)
        expected = json.dumps(
            build_provider_opencode_config(
                llm_config,
                disabled_tools=get_opencode_disabled_tools(),
                mcp_servers=mcp_servers,
                session_id=str(session.id),
            )
        )

        try:
            current = self._sandbox_manager.read_file(
                sandbox.id, session.id, "opencode.json"
            ).decode()
        except (UnicodeDecodeError, ValueError):
            current = None
        except RuntimeError:
            # Transient exec/API failure while merely checking; assume stale
            # and regenerate defensively rather than failing the turn.
            logger.warning(
                "Could not read opencode.json for session %s; regenerating",
                session.id,
            )
            current = None

        cache = get_cache_backend()
        dispose_pending_key = _dispose_pending_key(session.id)
        if current == expected:
            # A matching file does NOT prove the running opencode instance
            # picked it up: a prior reconcile may have written the file and
            # then failed the dispose. Retry the dispose while the marker is
            # set, else the instance stays on the old config until pod death.
            if (
                session.opencode_session_id is not None
                and cache.get(dispose_pending_key) is not None
            ):
                self._sandbox_manager.dispose_opencode_instance(sandbox.id, session.id)
            cache.delete(dispose_pending_key)
            if (
                session.agent_provider != llm_config.provider
                or session.agent_model != llm_config.model_name
            ):
                session.agent_provider = llm_config.provider
                session.agent_model = llm_config.model_name
                self._db_session.flush()
            return

        # Set the dispose-pending marker BEFORE writing the config: if we crash
        # after the write but before the dispose, the file will already match on
        # the next reconcile, so the marker is the only thing that tells it to
        # retry the missed dispose. Setting it after the write leaves that exact
        # window uncovered.
        mark_opencode_dispose_pending(session.id)
        self._sandbox_manager.regenerate_session_config(
            sandbox_id=sandbox.id,
            session_id=session.id,
            agent_provider=llm_config.provider,
            agent_model=llm_config.model_name,
            nextjs_port=session.nextjs_port,
            connectable_apps_section=build_connectable_apps_list(
                get_connectable_apps_for_user(self._db_session, user)
            ),
            user_name=user.personal_name,
            llm_config=llm_config,
            mcp_servers=mcp_servers,
        )
        if session.opencode_session_id is not None:
            self._sandbox_manager.dispose_opencode_instance(sandbox.id, session.id)
        cache.delete(dispose_pending_key)
        session.agent_provider = llm_config.provider
        session.agent_model = llm_config.model_name
        self._db_session.flush()

    def reload_session_skills(self, session_id: UUID, user: User) -> bool:
        """Reload one runtime and report whether its skills remain stale."""
        session = get_build_session(session_id, user.id, self._db_session)
        if session is None:
            raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Session not found")

        sandbox = get_sandbox_by_user_id(self._db_session, user.id)
        if sandbox is None or not session_runtime_stale(session, sandbox):
            return False

        skills_hash = sandbox.skills_hash
        mcp_config_hash = sandbox.mcp_config_hash
        if sandbox.status == SandboxStatus.PROVISIONING:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "Wait for the sandbox to finish starting before reloading skills.",
            )

        update_sandbox_heartbeat(self._db_session, sandbox.id)
        self._db_session.commit()

        prompt_slot = (
            self._sandbox_manager.prompt_slot(
                sandbox.id,
                session_id,
                acquire_timeout=0.1,
                fail_open=False,
            )
            if sandbox.status == SandboxStatus.RUNNING
            else nullcontext(PromptSlot(acquired=True))
        )
        with prompt_slot as slot:
            if not slot.acquired:
                raise OnyxError(
                    OnyxErrorCode.CONFLICT,
                    "Wait for the current turn to finish before reloading skills.",
                )

            if sandbox.status == SandboxStatus.RUNNING:
                try:
                    llm_config = self.session_llm_config(session, user)
                    mcp_servers = resolve_craft_mcp_servers(self._db_session, user)
                    # Rewrite the per-session opencode.json (provider catalog +
                    # current MCP set) and AGENTS.md BEFORE disposing so the
                    # fresh instance re-reads the current config.
                    self._sandbox_manager.regenerate_session_config(
                        sandbox_id=sandbox.id,
                        session_id=session_id,
                        agent_provider=session.agent_provider,
                        agent_model=session.agent_model,
                        nextjs_port=session.nextjs_port,
                        connectable_apps_section=build_connectable_apps_list(
                            get_connectable_apps_for_user(self._db_session, user)
                        ),
                        user_name=user.personal_name,
                        llm_config=llm_config,
                        mcp_servers=mcp_servers,
                    )
                    if session.opencode_session_id is not None:
                        self._sandbox_manager.dispose_opencode_instance(
                            sandbox.id, session_id
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to refresh skills for session %s",
                        session_id,
                        exc_info=True,
                    )
                    raise OnyxError(
                        OnyxErrorCode.BAD_GATEWAY,
                        "Failed to reload session.",
                    ) from exc

            session.skills_hash = skills_hash
            session.mcp_config_hash = mcp_config_hash
            self._db_session.flush()
            self._db_session.refresh(sandbox)
            return session_runtime_stale(session, sandbox)

    def ensure_sandbox_running(
        self,
        user_id: UUID,
        *,
        provisioning_wait_seconds: float = PROVISION_WAIT_SECONDS,
    ) -> Sandbox:
        """Ensure the user has a RUNNING sandbox, creating/waking as needed.

        Headless entry point for flows (e.g. scheduled tasks) that need the
        sandbox up but aren't going through ``create_session``.

        Behavior by current sandbox status:
        - No sandbox row: creates one and provisions it.
        - ``RUNNING`` + pod healthy: returns as-is.
        - ``RUNNING`` + pod missing/unhealthy: terminates and re-provisions
          under a new attempt number.
        - ``SLEEPING`` / ``TERMINATED`` / ``FAILED``: re-provisions in place.
        - ``PROVISIONING``: a dead attempt is taken over; a live one is
          polled up to ``provisioning_wait_seconds``. Raises
          ``SandboxProvisioningError`` only if the timeout elapses without
          a transition.

        Commits its own short transactions; the database session must be at a
        clean transaction boundary.

        Raises:
            SandboxProvisioningError: Provisioning failed, or the sandbox was
                still PROVISIONING after the wait timeout elapsed.
            ValueError: user missing.
        """
        sandbox, _outcome = ensure_sandbox_ready(
            self._db_session,
            self._sandbox_manager,
            user_id,
            policy=ProvisioningPolicy.POLL,
            provisioning_wait_seconds=provisioning_wait_seconds,
        )
        return sandbox

    def _ready_sandbox(self, user: User) -> tuple[Sandbox, SandboxReadyOutcome]:
        """Ensure the user's sandbox is RUNNING with current managed content.

        Fresh provisioning pushes managed content itself; a reused pod may be
        missing content pushed since it last synced.
        """
        sandbox, outcome = ensure_sandbox_ready(
            self._db_session,
            self._sandbox_manager,
            user.id,
            policy=ProvisioningPolicy.FAIL,
        )
        if outcome == SandboxReadyOutcome.ALREADY_RUNNING:
            sync_managed_content(
                self._db_session, self._sandbox_manager, sandbox.id, user
            )
        return sandbox, outcome

    def create_session(
        self,
        user_id: UUID,
        name: str | None = None,
        origin: SessionOrigin = SessionOrigin.INTERACTIVE,
    ) -> BuildSession:
        """Create a new build session with a ready sandbox.

        Reserve → reconcile → finalize: the session identity is committed as
        ``INITIALIZING`` (with its port reservation) before any workspace
        work, then flipped to ``ACTIVE`` only once the workspace and OpenCode
        session are usable. Failed initialization leaves a durable ``FAILED``
        row that a retry repairs under the same session ID.

        Args:
            user_id: The user ID
            name: Optional session name
            origin: Provenance of the session. INTERACTIVE (default) sessions
                appear in the Craft sidebar; SCHEDULED (scheduled-tasks
                executor) and SLACK (Slack bot) sessions are excluded.

        Raises:
            ValueError: If the user is missing
            OnyxError: If no LLM provider is accessible
            SandboxProvisioningError: If sandbox provisioning fails
            RuntimeError: If session initialization fails
        """
        user = fetch_user_by_id(self._db_session, user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Validate the model config before any reservation or external work;
        # the commit leaves the clean boundary ensure_sandbox_ready requires.
        llm_config = self.build_llm_configs(user)
        self._db_session.commit()

        sandbox, _outcome = self._ready_sandbox(user)

        # Reservation: commit the INITIALIZING identity and port before the
        # workspace exists.
        build_session = create_build_session__no_commit(
            user_id,
            self._db_session,
            name=name,
            origin=origin,
            agent_provider=llm_config.provider,
            agent_model=llm_config.model_name,
        )
        # Port allocation is skipped for non-interactive origins (SCHEDULED,
        # SLACK): those sessions are headless, never attach a preview, and
        # pile up fast enough to exhaust the [3010, 3100) range on a busy
        # tenant.
        if origin == SessionOrigin.INTERACTIVE:
            reserve_nextjs_port__no_commit(self._db_session, build_session)
        self._db_session.commit()
        logger.info(
            "Reserved build session %s for user %s (port: %s)",
            build_session.id,
            user_id,
            build_session.nextjs_port,
        )

        self._reconcile_session(sandbox, build_session, user, llm_config)
        return build_session

    def get_or_create_empty_session(
        self,
        user_id: UUID,
        name: str | None = None,
        headless: bool = False,
    ) -> BuildSession:
        """Get or create the user's empty (pre-provisioned) session.

        Used for pre-provisioning sandboxes when the user lands on /build/v1.
        The empty-session identity is reserved (or reused) under the per-user
        row lock, so concurrent pre-provisioners converge on one committed
        session. An existing session with an intact workspace is reused;
        otherwise it is repaired in place — returned to ``INITIALIZING`` and
        its workspace rebuilt under the same committed session ID (never
        deleted and replaced).

        Args:
            user_id: The user whose empty session should be reserved.
            name: Optional name to apply to a new or reused empty session.
            headless: Skip reserving a Next.js preview port when true.

        Raises:
            ValueError: If the user is missing
            OnyxError: If no LLM provider is accessible
            SandboxProvisioningError: If sandbox provisioning fails
            RuntimeError: If session initialization fails
        """
        user = fetch_user_by_id(self._db_session, user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Reservation: the user-row lock serializes concurrent
        # pre-provisioners so exactly one empty-session identity exists.
        locked_user = fetch_user_by_id(self._db_session, user_id, for_update=True)
        if locked_user is None:
            raise ValueError(f"User {user_id} not found")
        existing = get_empty_session_for_user(user_id, self._db_session)

        if existing is None:
            # Validates the model configuration before any external work.
            llm_config = self.build_llm_configs(user)
            session = create_build_session__no_commit(
                user_id,
                self._db_session,
                name=name,
                agent_provider=llm_config.provider,
                agent_model=llm_config.model_name,
            )
            if not headless:
                reserve_nextjs_port__no_commit(self._db_session, session)
            self._db_session.commit()
            logger.info("Reserved empty session %s for user %s", session.id, user_id)
            sandbox, _outcome = self._ready_sandbox(user)
            self._reconcile_session(sandbox, session, user, llm_config)
            return session

        session = existing
        if name is not None:
            session.name = name
        self._db_session.commit()
        logger.info(
            "Found existing empty session %s (status=%s) for user %s",
            session.id,
            session.status.value,
            user_id,
        )

        sandbox, outcome = self._ready_sandbox(user)
        workspace_intact = self._sandbox_manager.session_workspace_exists(
            sandbox.id, session.id
        )
        if (
            session.status == BuildSessionStatus.ACTIVE
            and outcome == SandboxReadyOutcome.ALREADY_RUNNING
            and workspace_intact
        ):
            # Light path: everything is already in place; refresh the
            # session runtime and hand the session back.
            self.reconcile_session_llm_config(sandbox, session, user)
            self._prewarm_opencode_session(sandbox, session)
            self._db_session.commit()
            logger.info(
                "Returning existing empty session %s for user %s",
                session.id,
                user_id,
            )
            return session

        # Repair: return the committed session ID to INITIALIZING and
        # rebuild its workspace, honoring its persisted model selection.
        logger.info(
            "Repairing empty session %s for user %s (status=%s, workspace %s)",
            session.id,
            user_id,
            session.status.value,
            "intact" if workspace_intact else "missing",
        )
        llm_config = self.session_llm_config(session, user)
        mark_session_initializing__no_commit(self._db_session, session)
        if session.nextjs_port is None and not headless:
            reserve_nextjs_port__no_commit(self._db_session, session)
        self._db_session.commit()

        self._reconcile_session(sandbox, session, user, llm_config)
        return session

    def _reconcile_session(
        self,
        sandbox: Sandbox,
        session: BuildSession,
        user: User,
        llm_config: CraftLLMProviderConfig,
    ) -> None:
        """Build the workspace and OpenCode session for a committed
        ``INITIALIZING`` session, then mark it ``ACTIVE`` (a no-op if the
        session already moved on).

        All database reads happen up front; the workspace setup and OpenCode
        prewarm run with no open transaction. On failure the session is
        durably marked ``FAILED`` (the sandbox stays ``RUNNING``) and the
        error is re-raised; a later request repairs the same session ID.
        """
        session_id = session.id
        try:
            connectable_apps_section = build_connectable_apps_list(
                get_connectable_apps_for_user(self._db_session, user)
            )
            mcp_servers = resolve_craft_mcp_servers(self._db_session, user)
            nextjs_port = session.nextjs_port
            opencode_session_id = session.opencode_session_id
            user_name = user.personal_name
            sandbox_skills_hash = sandbox.skills_hash
            sandbox_mcp_config_hash = sandbox.mcp_config_hash
            self._db_session.commit()

            logger.info(
                "Setting up session workspace %s in sandbox %s",
                session_id,
                sandbox.id,
            )
            self._sandbox_manager.setup_session_workspace(
                sandbox_id=sandbox.id,
                session_id=session_id,
                llm_config=llm_config,
                nextjs_port=nextjs_port,
                connectable_apps_section=connectable_apps_section,
                user_name=user_name,
                mcp_servers=mcp_servers,
            )
            minted_opencode_session_id = self._sandbox_manager.ensure_opencode_session(
                sandbox_id=sandbox.id,
                session_id=session_id,
                opencode_session_id=opencode_session_id,
            )
            if minted_opencode_session_id is None:
                raise RuntimeError(
                    f"Failed to prewarm opencode session for build session {session_id}"
                )

            finalized = finalize_session_initialization__no_commit(
                self._db_session,
                session_id,
                BuildSessionStatus.ACTIVE,
                opencode_session_id=minted_opencode_session_id,
                skills_hash=sandbox_skills_hash,
                mcp_config_hash=sandbox_mcp_config_hash,
            )
            if not finalized:
                self._db_session.rollback()
                raise StaleProvisioningAttemptError(
                    f"Session {session_id} left INITIALIZING before this "
                    f"attempt finalized"
                )
            self._db_session.commit()
            self._db_session.refresh(session)
            logger.info(
                "Successfully created session %s with workspace in sandbox %s",
                session_id,
                sandbox.id,
            )
        except StaleProvisioningAttemptError:
            raise
        except Exception as e:
            self._db_session.rollback()
            try:
                if finalize_session_initialization__no_commit(
                    self._db_session, session_id, BuildSessionStatus.FAILED
                ):
                    self._db_session.commit()
                    logger.error(
                        "Session %s initialization failed; marked FAILED "
                        "for repair on retry: %s",
                        session_id,
                        e,
                    )
                else:
                    self._db_session.rollback()
            except Exception:
                self._db_session.rollback()
                logger.exception(
                    "Failed to record initialization failure for session %s",
                    session_id,
                )
            raise

    def get_session(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> BuildSession | None:
        """
        Get a specific build session.

        Also updates the last activity timestamp.

        Args:
            session_id: The session UUID
            user_id: The user ID

        Returns:
            BuildSession model or None if not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session:
            update_session_activity(session_id, self._db_session)
            self._db_session.refresh(session)
        return session

    def generate_session_name(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> str | None:
        """
        Generate a session name using LLM based on the first user message.

        Args:
            session_id: The session UUID
            user_id: The user ID (for ownership verification)

        Returns:
            Generated session name or None if session not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        return generate_session_name(self._db_session, session_id)

    def update_session_name(
        self,
        session_id: UUID,
        user_id: UUID,
        name: str | None = None,
    ) -> BuildSession | None:
        """
        Update the name of a build session.

        If name is None, auto-generates a name using LLM based on the first
        user message in the session.

        Args:
            session_id: The session UUID
            user_id: The user ID
            name: The new session name (if None, auto-generates using LLM)

        Returns:
            Updated BuildSession model or None if not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        if name is not None:
            # Manual rename
            session.name = name
        else:
            # Auto-generate name from first user message using LLM
            session.name = generate_session_name(self._db_session, session_id)

        update_session_activity(session_id, self._db_session)
        self._db_session.commit()
        self._db_session.refresh(session)
        return session

    def delete_session(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        Delete a build session and all associated data.

        Cleans up session workspace but does NOT terminate the sandbox
        (sandbox is user-owned and shared across sessions).

        NOTE: This method does NOT commit the transaction. The caller is
        responsible for committing after this method returns successfully.

        Args:
            session_id: The session UUID
            user_id: The user ID

        Returns:
            True if deleted, False if not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return False

        # Get user's sandbox to clean up session workspace
        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        prompt_slot_cm: AbstractContextManager[PromptSlot]
        if sandbox and sandbox.status.is_active():
            prompt_slot_cm = self._sandbox_manager.prompt_slot(sandbox.id, session_id)
        else:
            prompt_slot_cm = nullcontext(PromptSlot(acquired=True))

        with prompt_slot_cm as slot, contextlib.ExitStack() as cleanup:
            if not slot.acquired:
                raise OnyxError(
                    OnyxErrorCode.CONFLICT,
                    "This session is busy with an active turn. Try again when it finishes.",
                )

            # Workspace/snapshot cleanup below can outlast one lease.
            slot_renewal_stop = threading.Event()
            cleanup.callback(slot_renewal_stop.set)
            start_thread_with_context(
                target=slot.keep_alive,
                name=f"delete-slot-renewal-{session_id}",
                daemon=True,
                args=(slot_renewal_stop, PROMPT_SLOT_KEEP_ALIVE_MAX_SECONDS),
            )

            def ensure_prompt_slot_owned() -> None:
                if slot.lost:
                    raise OnyxError(
                        OnyxErrorCode.CONFLICT,
                        "Session cleanup lost exclusive access. Try again.",
                    )

            if sandbox and sandbox.status.is_active():
                ensure_prompt_slot_owned()
                if session.opencode_session_id:
                    try:
                        deleted_from_opencode = (
                            self._sandbox_manager.delete_opencode_session(
                                sandbox.id,
                                session_id,
                                session.opencode_session_id,
                            )
                        )
                        if not deleted_from_opencode:
                            logger.warning(
                                "Best-effort opencode session delete returned false "
                                "for build session %s opencode session %s",
                                session_id,
                                session.opencode_session_id,
                            )
                    except Exception as e:
                        logger.warning(
                            "Best-effort opencode session delete failed for "
                            "build session %s opencode session %s: %s",
                            session_id,
                            session.opencode_session_id,
                            e,
                        )

                ensure_prompt_slot_owned()

                # Clean up session workspace (but don't terminate sandbox)
                try:
                    self._sandbox_manager.cleanup_session_workspace(
                        sandbox_id=sandbox.id,
                        session_id=session_id,
                    )
                    logger.info(
                        "Cleaned up session workspace %s in sandbox %s",
                        session_id,
                        sandbox.id,
                    )
                except Exception as e:
                    # Log but don't fail - session can still be deleted even if
                    # workspace cleanup fails (e.g., if pod is already terminated)
                    logger.warning(
                        "Failed to cleanup session workspace %s: %s",
                        session_id,
                        e,
                        exc_info=True,
                    )

                ensure_prompt_slot_owned()

            # Delete snapshot files from FileStore before removing DB records
            snapshots = get_snapshots_for_session(self._db_session, session_id)
            if snapshots:
                snapshot_manager = SnapshotManager(get_default_file_store())
                for snapshot in snapshots:
                    ensure_prompt_slot_owned()
                    try:
                        snapshot_manager.delete_snapshot(snapshot.storage_path)
                    except Exception as e:
                        logger.warning(
                            "Failed to delete snapshot file %s: %s",
                            snapshot.storage_path,
                            e,
                        )

            # Delete session (uses flush, caller commits)
            ensure_prompt_slot_owned()
            return delete_build_session__no_commit(
                session_id, user_id, self._db_session
            )

    # =========================================================================
    # Message Operations
    # =========================================================================

    def list_messages(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> list[BuildMessage] | None:
        """
        Get all messages for a session.

        Args:
            session_id: The session UUID
            user_id: The user ID

        Returns:
            List of BuildMessage models or None if session not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None
        return get_session_messages(session_id, self._db_session)

    def send_subagent_message(
        self,
        session_id: UUID,
        user_id: UUID,
        subagent_opencode_session_id: str,
        content: str,
    ) -> Generator[str, None, None]:
        """Send a follow-up to a subagent child session. Events are
        tagged with routing ``_meta`` so the frontend reloads them
        under the subagent."""
        yield from _streaming.stream_subagent_turn(
            self._db_session,
            self._sandbox_manager,
            session_id,
            subagent_opencode_session_id,
            content,
            user_id,
        )

    def interrupt_message(self, session_id: UUID, user_id: UUID) -> bool:
        """Interrupt the in-flight agent turn for a session.

        Two complementary signals: the interrupt fence covers the whole turn
        lifecycle (a turn that hasn't POSTed its prompt yet cancels at the
        fence check; the runner's consume loop polls it ~1/s and records the
        turn CANCELLED), and a direct best-effort abort to opencode stops the
        sandbox-side work even when no live runner is polling the fence
        (dead/blocked runner, other replica).
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Session not found")

        request_interrupt(session_id, get_cache_backend())

        if session.opencode_session_id:
            sandbox = get_sandbox_by_user_id(self._db_session, user_id)
            if sandbox is not None and sandbox.status.is_active():
                start_thread_with_context(
                    target=self._sandbox_manager.abort_opencode_session,
                    name=f"interrupt-abort-{session_id}",
                    daemon=True,
                    args=(sandbox.id, session_id, session.opencode_session_id),
                )
        return True

    def subscribe_to_existing_session_events(
        self,
        session_id: UUID,
        user_id: UUID,
        *,
        keepalive_seconds: float = 15.0,
        include_approval_announces: bool = True,
    ) -> Generator[str, None, None]:
        """Attach to an existing opencode session and stream translated ACP SSE.

        Used by scheduled-run viewers: the Celery executor is already driving
        the prompt, so this path only subscribes to the pod-wide event stream and
        filters by the session's persisted opencode session id. It deliberately
        does not persist events because the executor remains the durable writer.
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session not found")

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None or sandbox.status != SandboxStatus.RUNNING:
            raise OnyxError(
                OnyxErrorCode.SERVICE_UNAVAILABLE,
                "Sandbox is not running. Please wait for it to start.",
            )

        opencode_session_id = session.opencode_session_id
        if not opencode_session_id:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "Session live stream is not ready yet.",
            )

        raw_events = self._sandbox_manager.subscribe_to_opencode_session(
            sandbox.id,
            opencode_session_id,
            directory=f"/workspace/sessions/{session_id}",
            keepalive_seconds=keepalive_seconds,
        )
        if include_approval_announces:
            raw_events = self.merge_events_with_announces(
                raw_events,
                session_id=session_id,
                tenant_id=get_current_tenant_id(),
            )

        for acp_event in raw_events:
            yield _streaming.event_to_sse(acp_event)

    # ----- Persistence helpers (shared with the headless scheduled-tasks executor) -----
    #
    # `yield_sandbox_events` is a thin wrapper around the sandbox manager that drives
    # the agent to completion and yields raw sandbox events. It does NO database
    # writes, no SSE formatting — making it composable: the SSE endpoint wraps
    # it with `persist_sandbox_event` + an SSE formatter, and the headless
    # scheduled-tasks executor reuses `persist_sandbox_event` directly so the
    # persisted transcript is identical to an interactive run.

    def prompt_slot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        acquire_timeout: float = PROMPT_SLOT_FAST_FAIL_ACQUIRE_SECONDS,
    ) -> AbstractContextManager[PromptSlot]:
        return self._sandbox_manager.prompt_slot(
            sandbox_id, session_id, acquire_timeout=acquire_timeout
        )

    def yield_sandbox_events(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        user_message_content: str,
        attachments: list[PromptAttachment] | None = None,
        should_interrupt: Callable[[], bool] | None = None,
        should_abort_on_teardown: Callable[[], bool] | None = None,
        turn_timeout_seconds: float | None = None,
    ) -> Generator[Any, None, None]:
        build_session = _streaming.load_turn_session(
            self._db_session, self._sandbox_manager, sandbox_id, session_id
        )
        if build_session is None:
            return
        yield from _streaming.yield_sandbox_events(
            self._db_session,
            self._sandbox_manager,
            sandbox_id,
            session_id,
            user_message_content,
            attachments=attachments,
            opencode_session_id=build_session.opencode_session_id,
            agent_provider=build_session.agent_provider,
            agent_model=build_session.agent_model,
            should_interrupt=should_interrupt,
            should_abort_on_teardown=should_abort_on_teardown,
            turn_timeout_seconds=turn_timeout_seconds,
        )

    def merge_events_with_announces(
        self,
        event_iter: Generator[Any, None, None],
        *,
        session_id: UUID,
        tenant_id: str,
    ) -> Generator[Any, None, None]:
        yield from _streaming.merge_events_with_announces(
            event_iter,
            session_id=session_id,
            tenant_id=tenant_id,
        )

    def persist_sandbox_event(
        self,
        session_id: UUID,
        state: BuildStreamingState,
        sandbox_event: Any,
        routing_meta: dict[str, Any] | None = None,
    ) -> None:
        _streaming.persist_sandbox_event(
            self._db_session, session_id, state, sandbox_event, routing_meta
        )

    def finalize_persist(
        self,
        session_id: UUID,
        state: BuildStreamingState,
        routing_meta: dict[str, Any] | None = None,
    ) -> None:
        _streaming.finalize_persist(self._db_session, session_id, state, routing_meta)

    def persist_turn_error(
        self,
        session_id: UUID,
        turn_index: int,
        message: str,
    ) -> None:
        """User-visible error row so a failed turn still explains itself
        after reload (the live SSE error dies with the stream)."""
        create_message(
            session_id=session_id,
            message_type=MessageType.ASSISTANT,
            turn_index=turn_index,
            message_metadata={
                "type": "error",
                "message": message,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            },
            db_session=self._db_session,
        )

    def stamp_turn_deadline(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        *,
        soft_budget_seconds: int,
        hard_cap_seconds: int,
    ) -> None:
        self._sandbox_manager.stamp_turn_deadline(
            sandbox_id,
            session_id,
            soft_budget_seconds=soft_budget_seconds,
            hard_cap_seconds=hard_cap_seconds,
        )

    def clear_turn_deadline(self, sandbox_id: UUID, session_id: UUID) -> None:
        self._sandbox_manager.clear_turn_deadline(sandbox_id, session_id)

    # =========================================================================
    # Artifact Operations
    # =========================================================================

    def _resolve_owned_session_and_sandbox(
        self, session_id: UUID, user_id: UUID
    ) -> tuple[BuildSession, Sandbox] | None:
        """Resolve ``(session, sandbox)`` for an owned session, or ``None`` if
        either is missing — the caller surfaces ``None`` as a 404."""
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None
        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            return None
        return session, sandbox

    def _require_session_and_sandbox(
        self, session_id: UUID, user_id: UUID
    ) -> tuple[BuildSession, Sandbox]:
        """Like :meth:`_resolve_owned_session_and_sandbox` but raises
        ``ValueError`` instead of returning ``None`` (for mutating callers)."""
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise ValueError("Session not found")
        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            raise ValueError("Sandbox not found")
        return session, sandbox

    def _walk_sandbox_dir(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        base_dir: str,
        arcname_for: Callable[[str], str],
    ) -> list[tuple[str, str]]:
        """Recursively collect ``(workspace_path, arcname)`` for every file
        under ``base_dir``. Missing subdirectories are skipped."""
        collected: list[tuple[str, str]] = []

        def _walk(dir_path: str) -> None:
            try:
                entries = self._sandbox_manager.list_directory(
                    sandbox_id=sandbox_id, session_id=session_id, path=dir_path
                )
            except ValueError:
                return
            for entry in entries:
                if _is_hidden_workspace_entry(entry):
                    continue
                if entry.is_directory:
                    _walk(entry.path)
                else:
                    collected.append((entry.path, arcname_for(entry.path)))

        _walk(base_dir)
        return collected

    def _zip_files(
        self, sandbox_id: UUID, session_id: UUID, files: list[tuple[str, str]]
    ) -> bytes:
        """Build a deflate-compressed zip from ``(workspace_path, arcname)``
        pairs. Unreadable files are skipped."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for workspace_path, arcname in files:
                try:
                    content = self._sandbox_manager.read_file(
                        sandbox_id=sandbox_id,
                        session_id=session_id,
                        path=workspace_path,
                    )
                    zip_file.writestr(arcname, content)
                except ValueError:
                    continue
        return buffer.getvalue()

    def list_artifacts(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> list[dict[str, Any]] | None:
        """
        List artifacts generated in a session.

        Returns artifacts in the format expected by the frontend (matching ArtifactResponse).

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership

        Returns:
            List of artifact dicts or None if session not found or user doesn't own session
        """
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        artifacts: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        try:
            output_entries = self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id,
                session_id=session_id,
                path="outputs",
            )
        except ValueError:
            # outputs/ doesn't exist yet — no artifacts.
            return artifacts
        except Exception:
            # Sandbox transiently unreachable — degrade to no artifacts, not 500.
            logger.warning(
                "Could not list artifacts for session %s; sandbox not reachable",
                session_id,
                exc_info=True,
            )
            return artifacts

        # Check for webapp (web directory in outputs)
        has_webapp = any(
            entry.is_directory and entry.name == "web" for entry in output_entries
        )

        if has_webapp:
            artifacts.append(
                {
                    "id": str(uuid.uuid4()),
                    "session_id": str(session_id),
                    "type": "web_app",  # Use web_app to match streaming packet type
                    "name": "Web Application",
                    "path": "outputs/web",
                    "preview_url": None,  # Preview is via webapp URL, not artifact preview
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
            )

        return artifacts

    def download_artifact(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> tuple[bytes, str, str] | None:
        """
        Download a specific artifact file.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the artifact (within session workspace)

        Returns:
            Tuple of (content, mime_type, filename) or None if not found

        Raises:
            ValueError: If path traversal attempted or path is a directory
        """
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        # Extract filename from path
        filename = Path(path).name

        # Filter out opencode.json files
        if filename == "opencode.json":
            return None

        # Use sandbox manager to read file (works for both local and K8s)
        try:
            content = self._sandbox_manager.read_file(
                sandbox_id=sandbox.id,
                session_id=session_id,
                path=path,
            )
        except ValueError as e:
            # read_file raises ValueError for not found or directory
            if "Not a file" in str(e):
                raise ValueError("Cannot download directory")
            return None

        mime_type, _ = mimetypes.guess_type(filename)

        return (content, mime_type or "application/octet-stream", filename)

    def export_docx(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> tuple[bytes, str] | None:
        """
        Export a markdown file as DOCX.

        Reads the markdown file and converts it to DOCX.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the markdown file

        Returns:
            Tuple of (docx_bytes, filename) or None if not found

        Raises:
            ValueError: If path traversal attempted, file is not markdown, etc.
        """
        result = self.download_artifact(session_id, user_id, path)
        if result is None:
            return None

        content_bytes, _mime_type, filename = result

        if not filename.lower().endswith(".md"):
            raise ValueError("Only markdown (.md) files can be exported as DOCX")

        md_text = content_bytes.decode("utf-8")

        docx_bytes = markdown_to_docx_bytes(md_text)

        docx_filename = filename.rsplit(".", 1)[0] + ".docx"
        return (docx_bytes, docx_filename)

    def get_pptx_preview(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> dict[str, Any] | None:
        """
        Generate slide image previews for a PowerPoint file.

        Converts the presentation to individual JPEG slide images using
        soffice + pdftoppm, with caching to avoid re-conversion.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the PowerPoint file within session workspace

        Returns:
            Dict with slide_count, slide_paths, and cached flag,
            or None if session not found.

        Raises:
            ValueError: If path is invalid or conversion fails
        """
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        # Validate file extension
        if Path(path).suffix.lower() not in {".ppt", ".pptx"}:
            raise ValueError("Only .ppt and .pptx files are supported for preview")

        # Compute cache directory from path hash
        path_hash = hashlib.sha256(path.encode()).hexdigest()[:12]
        cache_dir = f"outputs/.pptx-preview/{path_hash}"

        slide_paths, cached = self._sandbox_manager.generate_pptx_preview(
            sandbox_id=sandbox.id,
            session_id=session_id,
            pptx_path=path,
            cache_dir=cache_dir,
        )

        return {
            "slide_count": len(slide_paths),
            "slide_paths": slide_paths,
            "cached": cached,
        }

    def get_webapp_info(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any] | None:
        """
        Get webapp information for a session.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership

        Returns:
            Dict with has_webapp, webapp_url, status, and ready,
            or None if session not found
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            return {
                "has_webapp": None,
                "webapp_url": None,
                "status": "no_sandbox",
                "ready": False,
                "sharing_scope": session.sharing_scope,
            }

        has_webapp = (
            self._has_scaffolded_webapp(sandbox.id, session_id)
            if sandbox.status == SandboxStatus.RUNNING
            else None
        )
        # Return the proxy URL - the proxy handles routing to the correct sandbox
        # for both local and Kubernetes environments.
        webapp_url = None
        ready = False
        if has_webapp and session.nextjs_port:
            webapp_url = f"{WEB_DOMAIN}/api/build/sessions/{session_id}/webapp"
            ready = self._check_nextjs_ready(
                sandbox.id, session_id, session.nextjs_port
            )

        return {
            "has_webapp": has_webapp,
            "webapp_url": webapp_url,
            "status": sandbox.status.value,
            "ready": ready,
            "sharing_scope": session.sharing_scope,
        }

    def _has_scaffolded_webapp(self, sandbox_id: UUID, session_id: UUID) -> bool | None:
        """Return True if ``outputs/web/package.json`` exists in the session."""
        try:
            entries = self._sandbox_manager.list_directory(
                sandbox_id=sandbox_id,
                session_id=session_id,
                path=_WEBAPP_DIRECTORY,
            )
        except ValueError:
            return False
        except RuntimeError:
            logger.warning(
                "Could not check webapp scaffold for session %s",
                session_id,
                exc_info=True,
            )
            return None

        return any(
            entry.name == _WEBAPP_PACKAGE_FILENAME and not entry.is_directory
            for entry in entries
        )

    def _check_nextjs_ready(
        self, sandbox_id: UUID, session_id: UUID, port: int
    ) -> bool:
        """Check if the NextJS dev server is responding.

        Probes a basePath-scoped dev-asset path with a short timeout: probing
        outside the basePath renders a spurious 404 page on every poll, and
        probing the app page itself would report not-ready whenever generated
        app code 500s (the iframe's error overlay is the right surface for
        that). A missing /_next/static asset returns a plain 404 without
        executing app code, so any response means the server is up.
        """
        try:
            sandbox_manager = get_sandbox_manager()
            internal_url = sandbox_manager.get_webapp_url(sandbox_id, port)
            probe_url = (
                f"{internal_url}/api/build/sessions/{session_id}/webapp"
                "/_next/static/onyx-ready-probe.js"
            )
            with httpx.Client(timeout=_WEBAPP_PROBE_TIMEOUT_SECONDS) as client:
                client.get(probe_url)
            return True
        except Exception:
            return False

    def download_webapp_zip(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> tuple[bytes, str] | None:
        """
        Create a zip file of the webapp directory.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership

        Returns:
            Tuple of (zip_bytes, filename) or None if session/webapp not found
        """
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        session, sandbox = resolved

        base_dir = "outputs/web"
        try:
            self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id,
                session_id=session_id,
                path=base_dir,
            )
        except ValueError:
            # Directory doesn't exist
            return None

        files = self._walk_sandbox_dir(
            sandbox.id,
            session_id,
            base_dir,
            arcname_for=lambda p: p[len(base_dir) + 1 :],
        )
        zip_bytes = self._zip_files(sandbox.id, session_id, files)

        session_name = session.name or f"session-{str(session_id)[:8]}"
        safe_name = _sanitize_zip_basename(session_name, allow_dots=False)
        return zip_bytes, f"{safe_name}-webapp.zip"

    def download_directory(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> tuple[bytes, str] | None:
        """
        Create a zip file of an arbitrary directory in the session workspace.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the directory (within session workspace)

        Returns:
            Tuple of (zip_bytes, filename) or None if session not found

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        try:
            self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id,
                session_id=session_id,
                path=path,
            )
        except ValueError:
            return None

        prefix_len = len(path) + 1  # +1 for trailing slash
        files = self._walk_sandbox_dir(
            sandbox.id,
            session_id,
            path,
            arcname_for=lambda p: p[prefix_len:],
        )
        zip_bytes = self._zip_files(sandbox.id, session_id, files)

        safe_name = _sanitize_zip_basename(Path(path).name, allow_dots=True)
        return zip_bytes, f"{safe_name}.zip"

    # =========================================================================
    # File System Operations
    # =========================================================================

    def list_directory(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> DirectoryListing | None:
        """
        List files and directories in the session workspace.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path from session workspace root (empty string for root)

        Returns:
            DirectoryListing with sorted entries (directories first) or None if not found

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        # Use sandbox manager to list directory (works for both local and K8s)
        # If the directory doesn't exist (e.g., session workspace not yet loaded),
        # return an empty listing rather than erroring out.
        try:
            raw_entries = self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id,
                session_id=session_id,
                path=path,
            )
        except ValueError as e:
            if "path traversal" in str(e).lower():
                raise
            return DirectoryListing(path=path, entries=[])

        # Filter hidden files and directories
        entries: list[FilesystemEntry] = [
            entry for entry in raw_entries if not _is_hidden_workspace_entry(entry)
        ]

        # Sort: directories first, then files, both alphabetically
        entries.sort(key=lambda e: (not e.is_directory, e.name.lower()))

        return DirectoryListing(path=path, entries=entries)

    def get_upload_stats(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> tuple[int, int]:
        """Get current file count and total size for a session's uploads.

        Delegates to SandboxManager for the actual filesystem query (supports both
        local filesystem and Kubernetes pods).

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership

        Returns:
            Tuple of (file_count, total_size_bytes)

        Raises:
            ValueError: If session not found
        """
        _, sandbox = self._require_session_and_sandbox(session_id, user_id)

        # Delegate to sandbox manager (handles both local and K8s)
        return self._sandbox_manager.get_upload_stats(
            sandbox_id=sandbox.id,
            session_id=session_id,
        )

    def upload_file(
        self,
        session_id: UUID,
        user_id: UUID,
        filename: str,
        content: bytes,
    ) -> tuple[str, int]:
        """Upload a file to the session's workspace.

        Delegates to SandboxManager for the actual file write (supports both
        local filesystem and Kubernetes pods).

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            filename: Sanitized filename (validation done at API layer)
            content: File content as bytes

        Returns:
            Tuple of (relative_path, size_bytes) where the file was saved

        Raises:
            ValueError: If session not found or upload limits exceeded
        """
        _, sandbox = self._require_session_and_sandbox(session_id, user_id)

        # Check upload limits
        file_count, total_size = self.get_upload_stats(session_id, user_id)

        if file_count >= MAX_UPLOAD_FILES_PER_SESSION:
            raise UploadLimitExceededError(
                f"Maximum number of files ({MAX_UPLOAD_FILES_PER_SESSION}) reached"
            )

        if total_size + len(content) > MAX_TOTAL_UPLOAD_SIZE_BYTES:
            max_mb = MAX_TOTAL_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise UploadLimitExceededError(
                f"Total upload size limit ({max_mb}MB) exceeded"
            )

        # Delegate to sandbox manager (handles both local and K8s)
        relative_path = self._sandbox_manager.upload_file(
            sandbox_id=sandbox.id,
            session_id=session_id,
            filename=filename,
            content=content,
        )

        # Update heartbeat - file upload is user activity that keeps sandbox alive
        update_sandbox_heartbeat(self._db_session, sandbox.id)
        self._db_session.commit()

        return relative_path, len(content)

    def delete_file(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> bool:
        """Delete a file from the session's workspace.

        Delegates to SandboxManager for the actual file delete (supports both
        local filesystem and Kubernetes pods).

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the file (e.g., "attachments/doc.pdf")

        Returns:
            True if file was deleted, False if not found

        Raises:
            ValueError: If session not found or path traversal attempted
        """
        _, sandbox = self._require_session_and_sandbox(session_id, user_id)

        # Delegate to sandbox manager (handles both local and K8s)
        deleted = self._sandbox_manager.delete_file(
            sandbox_id=sandbox.id,
            session_id=session_id,
            path=path,
        )

        if deleted:
            # SandboxManager already logs the deletion details
            # Update heartbeat - file deletion is user activity that keeps sandbox alive
            update_sandbox_heartbeat(self._db_session, sandbox.id)
            self._db_session.commit()

        return deleted
