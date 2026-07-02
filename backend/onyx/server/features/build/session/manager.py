"""Public interface for session operations.

SessionManager is the main entry point for build session lifecycle management.
It orchestrates session CRUD, message handling, artifact management, and file system access.
"""

import hashlib
import io
import mimetypes
import uuid
import zipfile
from collections.abc import Callable
from collections.abc import Generator
from contextlib import AbstractContextManager
from contextlib import nullcontext
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session as DBSession

from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.enums import SandboxStatus
from onyx.db.enums import SessionOrigin
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import MAX_TOTAL_UPLOAD_SIZE_BYTES
from onyx.server.features.build.configs import MAX_UPLOAD_FILES_PER_SESSION
from onyx.server.features.build.db.build_session import allocate_nextjs_port
from onyx.server.features.build.db.build_session import create_build_session__no_commit
from onyx.server.features.build.db.build_session import delete_build_session__no_commit
from onyx.server.features.build.db.build_session import (
    fetch_all_supported_build_llm_providers,
)
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.build_session import get_empty_session_for_user
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.build_session import get_user_build_sessions
from onyx.server.features.build.db.build_session import update_session_activity
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import get_snapshots_for_session
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.rate_limit import get_user_rate_limit_status
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.sandbox.models import DirectoryListing
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.user_library import hydrate_user_library
from onyx.server.features.build.session import sandbox_lifecycle as _sandbox
from onyx.server.features.build.session import streaming as _streaming
from onyx.server.features.build.session.errors import RateLimitError
from onyx.server.features.build.session.errors import UploadLimitExceededError
from onyx.server.features.build.session.interrupt_signal import request_interrupt
from onyx.server.features.build.session.llm_config import get_all_build_mode_llm_configs
from onyx.server.features.build.session.llm_config import select_default_llm_config
from onyx.server.features.build.session.md_to_docx import markdown_to_docx_bytes
from onyx.server.features.build.session.naming import generate_session_name
from onyx.server.features.build.session.streaming import BuildStreamingState
from onyx.skills.push import build_user_skills_payload
from onyx.skills.push import hydrate_sandbox_skills
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


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
}


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
    # Rate Limiting
    # =========================================================================

    def check_rate_limit(self, user: User) -> None:
        """
        Check build mode rate limits for a user.

        Args:
            user: The user to check rate limits for

        Raises:
            RateLimitError: If rate limit is exceeded
        """
        # Skip rate limiting for self-hosted deployments
        if not MULTI_TENANT:
            return

        rate_limit_status = get_user_rate_limit_status(user, self._db_session)
        if rate_limit_status.is_limited:
            raise RateLimitError(
                message=(
                    f"Rate limit exceeded. You have used "
                    f"{rate_limit_status.messages_used}/{rate_limit_status.limit} messages. "
                    f"Limit resets at {rate_limit_status.reset_timestamp}."
                    if rate_limit_status.reset_timestamp
                    else "This is a lifetime limit."
                ),
                messages_used=rate_limit_status.messages_used,
                limit=rate_limit_status.limit,
                reset_timestamp=rate_limit_status.reset_timestamp,
            )

    # =========================================================================
    # LLM Configuration
    # =========================================================================

    def build_llm_configs(
        self,
        user: User,
        requested_provider_type: str | None = None,
        requested_model_name: str | None = None,
    ) -> tuple[LLMProviderConfig, list[LLMProviderConfig]]:
        """Single access-scoped fetch → (default config, all pre-registered
        configs). ``configs[0]`` is the default. Used at provision time so the
        default and the cross-provider override list share one DB read.

        Raises:
            OnyxError: If no accessible supported provider is configured.
        """
        providers = fetch_all_supported_build_llm_providers(self._db_session, user)
        default = select_default_llm_config(
            providers, requested_provider_type, requested_model_name
        )
        return default, get_all_build_mode_llm_configs(providers, default)

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

    def _hydrate_skills(
        self, sandbox_id: UUID, user: User, files: FileSet | None = None
    ) -> None:
        try:
            hydrate_sandbox_skills(sandbox_id, user, self._db_session, files=files)
        except Exception:
            logger.warning(
                "Failed to push skills to sandbox %s", sandbox_id, exc_info=True
            )

    def _hydrate_user_library(self, sandbox_id: UUID, user_id: UUID) -> None:
        try:
            hydrate_user_library(sandbox_id, user_id, self._db_session)
        except Exception:
            logger.warning(
                "Failed to push user library to sandbox %s", sandbox_id, exc_info=True
            )

    def _prewarm_opencode_session(
        self, sandbox_id: UUID, session: BuildSession
    ) -> None:
        """Mint and persist the opencode-serve session before the first prompt.

        The caller owns the surrounding transaction. This keeps the empty Craft
        session's frontend-ready state aligned with the agent runtime being
        ready to accept the first user message.
        """
        opencode_session_id = self._sandbox_manager.ensure_opencode_session(
            sandbox_id=sandbox_id,
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
            self._db_session.flush()

    def ensure_sandbox_running(
        self,
        user_id: UUID,
        *,
        provisioning_wait_seconds: float = 30.0,
    ) -> Sandbox:
        """Ensure the user has a RUNNING sandbox, creating/waking as needed.

        Headless entry point for flows (e.g. scheduled tasks) that need the
        sandbox up but aren't going through ``create_session__no_commit``.
        Mirrors the sandbox-handling section of ``create_session__no_commit``
        but without creating a session record. Falls back to the system
        default LLM config since there is no user cookie context.

        Behavior by current sandbox status:
        - No sandbox row: creates one and provisions it.
        - ``RUNNING`` + pod healthy: returns as-is.
        - ``RUNNING`` + pod missing/unhealthy: terminates and re-provisions.
        - ``SLEEPING`` / ``TERMINATED`` / ``FAILED``: re-provisions in place.
        - ``PROVISIONING``: polls up to ``provisioning_wait_seconds`` (default
          30s) for the concurrent provisioner to finish, then continues
          based on the resulting status. Raises
          ``SandboxProvisioningError`` only if the timeout elapses without
          a transition.

        Honors ``SANDBOX_MAX_CONCURRENT_PER_ORG`` when ``MULTI_TENANT`` for
        any path that newly counts toward the running limit (creating a new
        sandbox or waking a SLEEPING / TERMINATED / FAILED one).

        Caller is responsible for committing.

        Raises:
            SandboxProvisioningError: Sandbox was still PROVISIONING after
                the wait timeout elapsed.
            ValueError: Max concurrent sandboxes reached, or user missing.
            RuntimeError: Sandbox manager failed to provision the pod.
        """
        user = fetch_user_by_id(self._db_session, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        _, all_llm_configs = self.build_llm_configs(user)
        return _sandbox.ensure_sandbox_ready(
            self._db_session,
            self._sandbox_manager,
            user_id,
            all_llm_configs,
            policy=_sandbox.ProvisioningPolicy.POLL,
            provisioning_wait_seconds=provisioning_wait_seconds,
            user=user,
        )

    def create_session__no_commit(
        self,
        user_id: UUID,
        name: str | None = None,
        llm_provider_type: str | None = None,
        llm_model_name: str | None = None,
        origin: SessionOrigin = SessionOrigin.INTERACTIVE,
        headless: bool = False,
    ) -> BuildSession:
        """
        Create a new build session with a sandbox.

        NOTE: This method does NOT commit the transaction. The caller is
        responsible for committing after this method returns successfully.
        This allows the entire operation to be atomic at the endpoint level.

        Args:
            user_id: The user ID
            name: Optional session name
            llm_provider_type: Provider type from user's cookie (e.g., "anthropic", "openai")
            llm_model_name: Model name from user's cookie (e.g., "claude-opus-4-5")
            origin: Provenance of the session. INTERACTIVE (default) sessions
                appear in the Craft sidebar; SCHEDULED sessions (created by
                the scheduled-tasks executor) are excluded.

        Returns:
            The created BuildSession model

        Raises:
            ValueError: If max concurrent sandboxes reached or no LLM provider
            RuntimeError: If sandbox provisioning fails
        """
        # Fetch user early — needed for provider access checks, PAT, AGENTS.md.
        user = fetch_user_by_id(self._db_session, user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Resolve the default + all pre-registered provider configs in one read.
        llm_config, all_llm_configs = self.build_llm_configs(
            user, llm_provider_type, llm_model_name
        )

        # Allocate port for this session (per-session port allocation).
        # Both LOCAL and KUBERNETES backends use the same port allocation
        # strategy. Skipped for SCHEDULED sessions: scheduled-task fires
        # are headless, never attach a preview, and pile up so fast they'd
        # exhaust the [3010, 3100) range on a busy tenant.
        nextjs_port: int | None
        if origin == SessionOrigin.SCHEDULED or headless:
            nextjs_port = None
        else:
            nextjs_port = allocate_nextjs_port(self._db_session)

        # Create BuildSession record with allocated port (uses flush, caller commits)
        build_session = create_build_session__no_commit(
            user_id,
            self._db_session,
            name=name,
            origin=origin,
            agent_provider=llm_config.provider,
            agent_model=llm_config.model_name,
        )
        build_session.nextjs_port = nextjs_port
        self._db_session.flush()
        session_id = str(build_session.id)
        logger.info(
            "Created build session %s for user %s (port: %s)",
            session_id,
            user_id,
            nextjs_port,
        )

        # Ensure the user's sandbox is RUNNING. Interactive callers can't
        # afford to wait through a concurrent provisioner, so we use the
        # FAIL policy (raise RuntimeError if another request is mid-
        # provision).
        sandbox = _sandbox.ensure_sandbox_ready(
            self._db_session,
            self._sandbox_manager,
            user_id,
            all_llm_configs,
            policy=_sandbox.ProvisioningPolicy.FAIL,
            user=user,
        )

        # Set up session workspace within the sandbox
        logger.info(
            "Setting up session workspace %s in sandbox %s", session_id, sandbox.id
        )
        user_name = user.personal_name

        skills_section, connectable_apps_section, skills_files = (
            build_user_skills_payload(user, self._db_session)
        )

        self._sandbox_manager.setup_session_workspace(
            sandbox_id=sandbox.id,
            session_id=build_session.id,
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            skills_section=skills_section,
            connectable_apps_section=connectable_apps_section,
            user_name=user_name,
        )
        self._hydrate_skills(sandbox.id, user, files=skills_files)
        self._hydrate_user_library(sandbox.id, user_id)
        self._prewarm_opencode_session(sandbox.id, build_session)

        logger.info(
            "Successfully created session %s with workspace in sandbox %s",
            session_id,
            sandbox.id,
        )

        return build_session

    def get_or_create_empty_session(
        self,
        user_id: UUID,
        llm_provider_type: str | None = None,
        llm_model_name: str | None = None,
        headless: bool = False,
    ) -> BuildSession:
        """Get existing empty session or create a new one with provisioned sandbox.

        Used for pre-provisioning sandboxes when user lands on /build/v1.
        Returns existing recent empty session if one exists and has a healthy sandbox.
        If an empty session exists but its sandbox is unhealthy/terminated/missing,
        the stale session is deleted and a fresh one is created (which will handle
        sandbox recovery/re-provisioning).

        Args:
            user_id: The user ID
            llm_provider_type: Provider type from user's cookie (e.g., "anthropic", "openai")
            llm_model_name: Model name from user's cookie (e.g., "claude-opus-4-5")

        Returns:
            BuildSession (existing empty or newly created)

        Raises:
            ValueError: If max concurrent sandboxes reached
            RuntimeError: If sandbox provisioning fails
        """
        existing = get_empty_session_for_user(user_id, self._db_session)
        if existing:
            logger.info(
                "Existing empty session %s found for user %s", existing.id, user_id
            )
            # Verify sandbox is healthy before returning existing session
            sandbox = get_sandbox_by_user_id(self._db_session, user_id)

            if sandbox and sandbox.status.is_active():
                # Quick health check to verify sandbox is actually responsive
                # AND verify the session workspace still exists on disk
                # (it may have been wiped if the sandbox was re-provisioned)
                is_healthy = self._sandbox_manager.health_check(sandbox.id, timeout=5.0)
                workspace_exists = (
                    is_healthy
                    and self._sandbox_manager.session_workspace_exists(
                        sandbox.id, existing.id
                    )
                )
                if is_healthy and workspace_exists:
                    user = fetch_user_by_id(self._db_session, user_id)
                    if user is None:
                        logger.warning("Cannot push skills: user %s not found", user_id)
                    else:
                        self._hydrate_skills(sandbox.id, user)
                    self._hydrate_user_library(sandbox.id, user_id)
                    self._prewarm_opencode_session(sandbox.id, existing)
                    logger.info(
                        "Returning existing empty session %s for user %s",
                        existing.id,
                        user_id,
                    )
                    return existing
                elif not is_healthy:
                    logger.warning(
                        "Empty session %s has unhealthy sandbox %s. Deleting and creating fresh session.",
                        existing.id,
                        sandbox.id,
                    )
                else:
                    logger.warning(
                        "Empty session %s workspace missing in sandbox %s. Deleting and creating fresh session.",
                        existing.id,
                        sandbox.id,
                    )
            else:
                logger.warning(
                    "Empty session %s has no active sandbox (sandbox=%s). Deleting and creating fresh session.",
                    existing.id,
                    "missing" if not sandbox else sandbox.status,
                )

            # Delete through the normal session path. Opencode history is
            # sandbox-global implementation data, so this removes the Onyx
            # session row without trying to prune opencode's internal store.
            self.delete_session(existing.id, user_id)

        return self.create_session__no_commit(
            user_id=user_id,
            llm_provider_type=llm_provider_type,
            llm_model_name=llm_model_name,
            headless=headless,
        )

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
        prompt_slot_cm: AbstractContextManager[bool]
        if sandbox and sandbox.status.is_active():
            prompt_slot_cm = self._sandbox_manager.prompt_slot(sandbox.id, session_id)
        else:
            prompt_slot_cm = nullcontext(True)

        with prompt_slot_cm as acquired_prompt_slot:
            if not acquired_prompt_slot:
                raise OnyxError(
                    OnyxErrorCode.CONFLICT,
                    "This session is busy with an active turn. Try again when it finishes.",
                )

            if sandbox and sandbox.status.is_active():
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
                        "Failed to cleanup session workspace %s: %s", session_id, e
                    )

            # Delete snapshot files from FileStore before removing DB records
            snapshots = get_snapshots_for_session(self._db_session, session_id)
            if snapshots:
                snapshot_manager = SnapshotManager(get_default_file_store())
                for snapshot in snapshots:
                    try:
                        snapshot_manager.delete_snapshot(snapshot.storage_path)
                    except Exception as e:
                        logger.warning(
                            "Failed to delete snapshot file %s: %s",
                            snapshot.storage_path,
                            e,
                        )

            # Delete session (uses flush, caller commits)
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

        Sets the interrupt fence and returns. The active stream's consume loop
        polls the fence (~1/s) and self-terminates — aborting opencode and
        emitting its own ``PromptResponse`` rather than waiting on a
        ``session.idle`` that may never arrive after an abort. A flag-based
        approach (vs. a direct abort) is safe to call at any point in the turn
        lifecycle, including before the stream has started consuming events.
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Session not found")

        request_interrupt(session_id, get_cache_backend())
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
    ) -> AbstractContextManager[bool]:
        return self._sandbox_manager.prompt_slot(sandbox_id, session_id)

    def yield_sandbox_events(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        user_message_content: str,
        should_interrupt: Callable[[], bool] | None = None,
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
            opencode_session_id=build_session.opencode_session_id,
            agent_provider=build_session.agent_provider,
            agent_model=build_session.agent_model,
            should_interrupt=should_interrupt,
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
        Generate slide image previews for a PPTX file.

        Converts the PPTX to individual JPEG slide images using
        soffice + pdftoppm, with caching to avoid re-conversion.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the PPTX file within session workspace

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
        if not path.lower().endswith(".pptx"):
            raise ValueError("Only .pptx files are supported for preview")

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
                "has_webapp": False,
                "webapp_url": None,
                "status": "no_sandbox",
                "ready": False,
                "sharing_scope": session.sharing_scope,
            }

        # Return the proxy URL - the proxy handles routing to the correct sandbox
        # for both local and Kubernetes environments
        webapp_url = None
        ready = False
        if session.nextjs_port:
            webapp_url = f"{WEB_DOMAIN}/api/build/sessions/{session_id}/webapp"

            # Quick health check: can the API server reach the NextJS dev server?
            ready = self._check_nextjs_ready(sandbox.id, session.nextjs_port)

        return {
            "has_webapp": session.nextjs_port is not None,
            "webapp_url": webapp_url,
            "status": sandbox.status.value,
            "ready": ready,
            "sharing_scope": session.sharing_scope,
        }

    def _check_nextjs_ready(self, sandbox_id: UUID, port: int) -> bool:
        """Check if the NextJS dev server is responding.

        Does a quick HTTP GET to the sandbox's internal URL with a short timeout.
        Returns True if the server responds with any status code, False on timeout
        or connection error.
        """
        try:
            sandbox_manager = get_sandbox_manager()
            internal_url = sandbox_manager.get_webapp_url(sandbox_id, port)
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(internal_url)
                # Any response (even 500) means the server is up
                return resp.status_code < 500
        except (httpx.TimeoutException, httpx.ConnectError, Exception):
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

        return deleted
