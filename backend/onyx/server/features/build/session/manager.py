"""Public ``SessionManager`` for the Craft build feature.

The class is the API surface that route handlers and background tasks
consume. Each method contains its own orchestration — the small set of
extracted modules (``streaming``, ``sandbox_lifecycle``, ``llm_config``,
``naming``, ``errors``) hold helpers that are either substantial or
genuinely shared across multiple methods. Pure ORM CRUD already lives
in ``onyx.server.features.build.db``; this layer composes it with
sandbox + LLM operations.

Several methods named with a leading underscore are part of an explicit
shared-persistence contract: the scheduled-tasks executor and the
external-dependency-unit tests reach into them by name to keep
scheduled-run transcripts byte-identical to interactive runs. See the
"Shared persistence layer" section at the bottom of the class.
"""

import hashlib
import io
import mimetypes
import uuid
import zipfile
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session as DBSession

from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.enums import SessionOrigin
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.api.models import DirectoryListing
from onyx.server.features.build.api.models import FileSystemEntry
from onyx.server.features.build.api.rate_limit import get_user_rate_limit_status
from onyx.server.features.build.configs import MAX_TOTAL_UPLOAD_SIZE_BYTES
from onyx.server.features.build.configs import MAX_UPLOAD_FILES_PER_SESSION
from onyx.server.features.build.db.build_session import allocate_nextjs_port
from onyx.server.features.build.db.build_session import create_build_session__no_commit
from onyx.server.features.build.db.build_session import delete_build_session__no_commit
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.build_session import get_empty_session_for_user
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.build_session import get_user_build_sessions
from onyx.server.features.build.db.build_session import update_session_activity
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import get_snapshots_for_session
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.sandbox.base import get_sandbox_manager
from onyx.server.features.build.sandbox.manager.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.session import sandbox_lifecycle as _sandbox
from onyx.server.features.build.session import streaming as _streaming
from onyx.server.features.build.session.errors import RateLimitError
from onyx.server.features.build.session.errors import SandboxProvisioningError
from onyx.server.features.build.session.errors import UploadLimitExceededError
from onyx.server.features.build.session.interrupt_signal import request_interrupt
from onyx.server.features.build.session.llm_config import get_all_build_mode_llm_configs
from onyx.server.features.build.session.llm_config import resolve_llm_configs
from onyx.server.features.build.session.md_to_docx import markdown_to_docx_bytes
from onyx.server.features.build.session.naming import generate_session_name
from onyx.server.features.build.session.sandbox_lifecycle import ProvisioningPolicy
from onyx.server.features.build.session.streaming import BuildStreamingState
from onyx.skills.push import build_user_skills_payload
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


__all__ = [
    "SessionManager",
    "BuildStreamingState",
    "RateLimitError",
    "UploadLimitExceededError",
    "SandboxProvisioningError",
    "get_all_build_mode_llm_configs",
]


# =============================================================================
# Module-private constants + helpers
# =============================================================================

# Filenames + directories the user shouldn't see in listings.
_HIDDEN_FILESYSTEM_PATTERNS = frozenset(
    {
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
)

# Files that never get exposed as downloadable artifacts, even when
# inside a workspace path the user asked for explicitly.
_HIDDEN_ARTIFACT_FILENAMES = frozenset({"opencode.json"})

# Health-check timeouts (seconds).
_HEALTHCHECK_TIMEOUT_SECONDS = 5.0
_NEXTJS_READY_TIMEOUT_SECONDS = 2.0


def _sanitize_zip_basename(name: str, *, allow_dots: bool) -> str:
    """Replace non-safe characters in a zip filename stem. ``allow_dots``
    keeps version-suffixed directory names like ``my.lib`` intact."""
    safe = {"-", "_"}
    if allow_dots:
        safe.add(".")
    return "".join(c if c.isalnum() or c in safe else "_" for c in name)


def _walk_sandbox_dir(
    sandbox_manager: Any,
    sandbox_id: UUID,
    session_id: UUID,
    base_dir: str,
    arcname_for: Callable[[str], str],
) -> list[tuple[str, str]]:
    """Recursively collect ``(workspace_path, arcname)`` for every file
    under ``base_dir``. Missing subdirectories are silently skipped."""
    collected: list[tuple[str, str]] = []

    def _walk(dir_path: str) -> None:
        try:
            entries = sandbox_manager.list_directory(
                sandbox_id=sandbox_id, session_id=session_id, path=dir_path
            )
        except ValueError:
            return
        for entry in entries:
            if entry.is_directory:
                _walk(entry.path)
            else:
                collected.append((entry.path, arcname_for(entry.path)))

    _walk(base_dir)
    return collected


def _zip_files(
    sandbox_manager: Any,
    sandbox_id: UUID,
    session_id: UUID,
    files: list[tuple[str, str]],
) -> bytes:
    """Build a deflate-compressed zip from ``(workspace_path, arcname)``
    pairs. Unreadable files are silently skipped."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for workspace_path, arcname in files:
            try:
                content = sandbox_manager.read_file(
                    sandbox_id=sandbox_id,
                    session_id=session_id,
                    path=workspace_path,
                )
                zip_file.writestr(arcname, content)
            except ValueError:
                continue
    return buffer.getvalue()


class SessionManager:
    """Per-request facade for build-session operations.

    Bound to a single SQLAlchemy session for the lifetime of the request
    (NOT a singleton). The sandbox manager is captured at construction
    time so test fixtures can swap it.

    Most methods are ``__no_commit`` and expect the caller (a FastAPI
    endpoint, typically) to commit when the request is otherwise
    successful. Two exceptions self-commit because they need a durable
    write-ahead before any downstream call can succeed; both are called
    out in their docstrings.
    """

    def __init__(self, db_session: DBSession) -> None:
        self._db_session = db_session
        self._sandbox_manager = get_sandbox_manager()

    # =========================================================================
    # Rate limiting
    # =========================================================================

    def check_rate_limit(self, user: User) -> None:
        """Raise :class:`RateLimitError` if the user has exhausted their
        build-mode message budget. No-op on self-hosted."""
        if not MULTI_TENANT:
            return
        status = get_user_rate_limit_status(user, self._db_session)
        if not status.is_limited:
            return
        if status.reset_timestamp:
            message = (
                f"Rate limit exceeded. You have used "
                f"{status.messages_used}/{status.limit} messages. "
                f"Limit resets at {status.reset_timestamp}."
            )
        else:
            message = "This is a lifetime limit."
        raise RateLimitError(
            message=message,
            messages_used=status.messages_used,
            limit=status.limit,
            reset_timestamp=status.reset_timestamp,
        )

    # =========================================================================
    # LLM configuration
    # =========================================================================

    def build_llm_configs(
        self,
        user: User,
        requested_provider_type: str | None = None,
        requested_model_name: str | None = None,
    ) -> tuple[LLMProviderConfig, list[LLMProviderConfig]]:
        """``(default, all_pre_registered)`` for ``user``. ``all[0]`` is
        the default. One access-scoped DB fetch shared by both."""
        return resolve_llm_configs(
            self._db_session, user, requested_provider_type, requested_model_name
        )

    # =========================================================================
    # Sandbox lifecycle
    # =========================================================================

    def ensure_sandbox_running(
        self,
        user_id: UUID,
        *,
        provisioning_wait_seconds: float = 30.0,
    ) -> Sandbox:
        """Headless entry point: ensure the user has a RUNNING sandbox,
        polling through ``PROVISIONING`` if a concurrent caller is
        already minting one.

        Unlike the interactive path, this falls back to the system-
        default LLM config because there's no user cookie context.
        Caller commits.
        """
        user = self._fetch_user(user_id)
        _, all_llm_configs = self.build_llm_configs(user)
        return _sandbox.ensure_sandbox_ready(
            self._db_session,
            self._sandbox_manager,
            user_id,
            all_llm_configs,
            policy=ProvisioningPolicy.POLL,
            provisioning_wait_seconds=provisioning_wait_seconds,
        )

    def terminate_user_sandbox(self, user_id: UUID) -> bool:
        """Tear down the user's sandbox (across all sessions). Used for
        explicit "start fresh" actions."""
        return _sandbox.terminate_user_sandbox(
            self._db_session, self._sandbox_manager, user_id
        )

    # =========================================================================
    # Session CRUD
    # =========================================================================

    def list_sessions(self, user_id: UUID) -> list[BuildSession]:
        """All build sessions for ``user_id``, most-recent first."""
        return get_user_build_sessions(user_id, self._db_session)

    def get_session(self, session_id: UUID, user_id: UUID) -> BuildSession | None:
        """Fetch a session and bump its last-activity timestamp (the
        read counts as user activity for sandbox-idle tracking)."""
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None
        update_session_activity(session_id, self._db_session)
        self._db_session.refresh(session)
        return session

    def create_session__no_commit(
        self,
        user_id: UUID,
        name: str | None = None,
        llm_provider_type: str | None = None,
        llm_model_name: str | None = None,
        origin: SessionOrigin = SessionOrigin.INTERACTIVE,
        headless: bool = False,
    ) -> BuildSession:
        """Create a new build session with a RUNNING sandbox and an on-
        disk workspace.

        Three phases:
        1. Resolve the LLM config + allocate a port + insert the
           ``BuildSession`` row.
        2. Ensure the sandbox is RUNNING (state machine, FAIL policy —
           interactive callers can't wait through a concurrent
           provisioning).
        3. Set up the per-session workspace + hydrate skills / library.

        Does NOT commit; the caller owns the transaction so all of the
        new rows land atomically.

        Raises:
            ValueError: user missing, concurrency cap hit, or no
                accessible LLM provider.
            RuntimeError: pod provisioning failed, or sandbox is already
                ``PROVISIONING`` under another request.
        """
        user = self._fetch_user(user_id)
        llm_config, all_llm_configs = self.build_llm_configs(
            user, llm_provider_type, llm_model_name
        )

        # Port allocation is skipped for SCHEDULED + headless sessions:
        # they never attach a preview and would otherwise burn through
        # the [3010, 3100) range on a busy tenant.
        nextjs_port = (
            None
            if origin == SessionOrigin.SCHEDULED or headless
            else allocate_nextjs_port(self._db_session)
        )

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
        logger.info(
            "Created build session %s for user %s (port=%s)",
            build_session.id,
            user_id,
            nextjs_port,
        )

        sandbox = _sandbox.ensure_sandbox_ready(
            self._db_session,
            self._sandbox_manager,
            user_id,
            all_llm_configs,
            policy=ProvisioningPolicy.FAIL,
        )

        skills_section, skills_files = build_user_skills_payload(user, self._db_session)
        self._sandbox_manager.setup_session_workspace(
            sandbox_id=sandbox.id,
            session_id=build_session.id,
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            skills_section=skills_section,
            snapshot_path=None,  # TODO: Support restoring from snapshot
            user_name=user.personal_name,
            user_role=user.personal_role,
        )
        _sandbox.hydrate_skills(self._db_session, sandbox.id, user, files=skills_files)
        _sandbox.hydrate_user_library_into_sandbox(
            self._db_session, sandbox.id, user_id
        )

        logger.info(
            "Successfully created session %s with workspace in sandbox %s",
            build_session.id,
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
        """Return a ready-to-use empty session, reusing a pre-
        provisioned one when its sandbox + workspace are still healthy.

        Used when the user lands on ``/build/v1`` — returning a recent
        healthy empty session avoids the cold-start cost of provisioning
        a new sandbox.
        """
        existing = get_empty_session_for_user(user_id, self._db_session)
        if existing is None:
            return self.create_session__no_commit(
                user_id=user_id,
                llm_provider_type=llm_provider_type,
                llm_model_name=llm_model_name,
                headless=headless,
            )

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is not None and sandbox.status.is_active():
            healthy = self._sandbox_manager.health_check(
                sandbox.id, timeout=_HEALTHCHECK_TIMEOUT_SECONDS
            )
            workspace_exists = (
                healthy
                and self._sandbox_manager.session_workspace_exists(
                    sandbox.id, existing.id
                )
            )
            if healthy and workspace_exists:
                # Re-hydrate skills + library in case they changed since
                # this empty session was provisioned.
                user = fetch_user_by_id(self._db_session, user_id)
                if user is None:
                    logger.warning("Cannot push skills: user %s not found", user_id)
                else:
                    _sandbox.hydrate_skills(self._db_session, sandbox.id, user)
                _sandbox.hydrate_user_library_into_sandbox(
                    self._db_session, sandbox.id, user_id
                )
                logger.info(
                    "Returning existing empty session %s for user %s",
                    existing.id,
                    user_id,
                )
                return existing
            logger.warning(
                "Empty session %s sandbox=%s is unhealthy or workspace "
                "missing; deleting and creating a fresh session",
                existing.id,
                sandbox.id,
            )
        else:
            logger.warning(
                "Empty session %s has no active sandbox; deleting and "
                "creating a fresh session",
                existing.id,
            )

        delete_build_session__no_commit(existing.id, user_id, self._db_session)
        return self.create_session__no_commit(
            user_id=user_id,
            llm_provider_type=llm_provider_type,
            llm_model_name=llm_model_name,
            headless=headless,
        )

    def delete_empty_session(self, user_id: UUID) -> bool:
        """Delete the user's pre-provisioned empty session (used when
        the LLM selection changes). Returns False if none existed."""
        empty_session = get_empty_session_for_user(user_id, self._db_session)
        if empty_session is None:
            logger.info("No empty session found for user %s", user_id)
            return False
        self._cleanup_session_workspace(user_id, empty_session)
        delete_build_session__no_commit(empty_session.id, user_id, self._db_session)
        logger.info("Deleted empty session %s for user %s", empty_session.id, user_id)
        return True

    def delete_session(self, session_id: UUID, user_id: UUID) -> bool:
        """Delete a session + clean up its workspace + snapshots. Does
        NOT terminate the sandbox (it's shared across sessions). Caller
        commits."""
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return False
        self._cleanup_session_workspace(user_id, session)
        self._cleanup_session_snapshots(session_id)
        return delete_build_session__no_commit(session_id, user_id, self._db_session)

    def _cleanup_session_workspace(self, user_id: UUID, session: BuildSession) -> None:
        """Best-effort cleanup of the per-session subdirectory inside
        the sandbox. Failures are logged — the session row can still be
        deleted even if the pod is gone or unreachable."""
        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None or not sandbox.status.is_active():
            return
        try:
            self._sandbox_manager.cleanup_session_workspace(
                sandbox_id=sandbox.id,
                session_id=session.id,
                nextjs_port=session.nextjs_port,
            )
            logger.info(
                "Cleaned up session workspace %s in sandbox %s",
                session.id,
                sandbox.id,
            )
        except Exception as e:
            logger.warning("Failed to cleanup session workspace %s: %s", session.id, e)

    def _cleanup_session_snapshots(self, session_id: UUID) -> None:
        snapshots = get_snapshots_for_session(self._db_session, session_id)
        if not snapshots:
            return
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

    # =========================================================================
    # Session naming
    # =========================================================================

    def generate_session_name(self, session_id: UUID, user_id: UUID) -> str | None:
        """LLM-generated name based on the first user message. ``None``
        if the session doesn't exist or isn't owned by ``user_id``."""
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
        """Set ``name`` (or auto-generate if ``None``). Commits — this
        is a user-driven mutation that should be visible immediately
        and isn't part of a larger transaction."""
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None
        if name is not None:
            session.name = name
        else:
            session.name = generate_session_name(self._db_session, session_id)
        update_session_activity(session_id, self._db_session)
        self._db_session.commit()
        self._db_session.refresh(session)
        return session

    # =========================================================================
    # Messages
    # =========================================================================

    def list_messages(
        self, session_id: UUID, user_id: UUID
    ) -> list[BuildMessage] | None:
        """All messages for a session, or ``None`` if the session
        doesn't exist / isn't owned by ``user_id``."""
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None
        return get_session_messages(session_id, self._db_session)

    def send_message(
        self,
        session_id: UUID,
        user_id: UUID,
        content: str,
    ) -> Generator[str, None, None]:
        """Send a message to the CLI agent and stream its response as
        SSE frames."""
        yield from _streaming.stream_cli_agent_turn(
            self._db_session,
            self._sandbox_manager,
            session_id,
            user_id,
            content,
        )

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
            user_id,
            subagent_opencode_session_id,
            content,
        )

    def interrupt_message(self, session_id: UUID, user_id: UUID) -> bool:
        """Interrupt the in-flight agent turn for a session.

        Sets a cache fence and returns. The active stream's consume
        loop polls the fence (~1s) and self-terminates — aborting
        opencode and emitting its own ``PromptResponse`` rather than
        waiting on a ``session.idle`` that may never arrive after an
        abort. Setting a flag (vs. a direct abort) is also what
        survives the first-turn race, where the opencode session id
        isn't minted until inside the stream.
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Session not found")
        request_interrupt(session_id, get_cache_backend())
        return True

    # =========================================================================
    # Artifacts
    # =========================================================================

    def list_artifacts(
        self, session_id: UUID, user_id: UUID
    ) -> list[dict[str, Any]] | None:
        """All artifacts (currently just the webapp, if present) for
        a session. Degrades to ``[]`` if the sandbox is unreachable."""
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        try:
            output_entries = self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id, session_id=session_id, path="outputs"
            )
        except ValueError:
            return []
        except Exception:
            logger.warning(
                "Could not list artifacts for session %s; sandbox unreachable",
                session_id,
                exc_info=True,
            )
            return []

        has_webapp = any(
            entry.is_directory and entry.name == "web" for entry in output_entries
        )
        if not has_webapp:
            return []

        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "id": str(uuid.uuid4()),
                "session_id": str(session_id),
                "type": "web_app",
                "name": "Web Application",
                "path": "outputs/web",
                # Preview is via the webapp URL, not artifact preview.
                "preview_url": None,
                "created_at": now,
                "updated_at": now,
            }
        ]

    def download_artifact(
        self, session_id: UUID, user_id: UUID, path: str
    ) -> tuple[bytes, str, str] | None:
        """Return ``(content, mime_type, filename)`` for a single file.

        Raises:
            ValueError: ``path`` is a directory.
        """
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        filename = Path(path).name
        if filename in _HIDDEN_ARTIFACT_FILENAMES:
            return None

        try:
            content = self._sandbox_manager.read_file(
                sandbox_id=sandbox.id, session_id=session_id, path=path
            )
        except ValueError as e:
            if "Not a file" in str(e):
                raise ValueError("Cannot download directory")
            return None

        mime_type, _ = mimetypes.guess_type(filename)
        return content, mime_type or "application/octet-stream", filename

    def export_docx(
        self, session_id: UUID, user_id: UUID, path: str
    ) -> tuple[bytes, str] | None:
        """Convert a markdown file to DOCX. Same ownership / missing
        semantics as :meth:`download_artifact`."""
        result = self.download_artifact(session_id, user_id, path)
        if result is None:
            return None
        content_bytes, _mime, filename = result
        if not filename.lower().endswith(".md"):
            raise ValueError("Only markdown (.md) files can be exported as DOCX")
        docx_bytes = markdown_to_docx_bytes(content_bytes.decode("utf-8"))
        return docx_bytes, filename.rsplit(".", 1)[0] + ".docx"

    def get_pptx_preview(
        self, session_id: UUID, user_id: UUID, path: str
    ) -> dict[str, Any] | None:
        """Generate (or fetch cached) JPEG slide previews for a PPTX
        file. Cache key is a SHA-256 prefix of the workspace path."""
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        if not path.lower().endswith(".pptx"):
            raise ValueError("Only .pptx files are supported for preview")

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

    def get_webapp_info(self, session_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        """Webapp readiness summary. Returns a partial response when
        the user has no sandbox, since the UI needs ``sharing_scope``
        even before a sandbox exists."""
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

        webapp_url: str | None = None
        ready = False
        if session.nextjs_port:
            webapp_url = f"{WEB_DOMAIN}/api/build/sessions/{session_id}/webapp"
            ready = self._check_nextjs_ready(sandbox.id, session.nextjs_port)
            # If not ready, ask the manager to ensure NextJS is running.
            # On the local backend this triggers a background restart so
            # the frontend poll eventually sees ready=True without user
            # action.
            if not ready:
                self._sandbox_manager.ensure_nextjs_running(
                    sandbox.id, session_id, session.nextjs_port
                )

        return {
            "has_webapp": session.nextjs_port is not None,
            "webapp_url": webapp_url,
            "status": sandbox.status.value,
            "ready": ready,
            "sharing_scope": session.sharing_scope,
        }

    def _check_nextjs_ready(self, sandbox_id: UUID, port: int) -> bool:
        """Quick HTTP probe of the in-sandbox NextJS dev server. Any
        response below 500 means the server is up."""
        try:
            internal_url = self._sandbox_manager.get_webapp_url(sandbox_id, port)
            with httpx.Client(timeout=_NEXTJS_READY_TIMEOUT_SECONDS) as client:
                resp = client.get(internal_url)
                return resp.status_code < 500
        except (httpx.TimeoutException, httpx.ConnectError):
            return False
        except Exception:
            return False

    def download_webapp_zip(
        self, session_id: UUID, user_id: UUID
    ) -> tuple[bytes, str] | None:
        """Zip ``outputs/web/`` from the session workspace. Arcnames
        are relative to the web directory."""
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        session, sandbox = resolved

        base_dir = "outputs/web"
        try:
            self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id, session_id=session_id, path=base_dir
            )
        except ValueError:
            return None

        files = _walk_sandbox_dir(
            self._sandbox_manager,
            sandbox.id,
            session_id,
            base_dir,
            arcname_for=lambda p: p[len(base_dir) + 1 :],
        )
        zip_bytes = _zip_files(self._sandbox_manager, sandbox.id, session_id, files)

        safe_name = _sanitize_zip_basename(
            session.name or f"session-{str(session_id)[:8]}", allow_dots=False
        )
        return zip_bytes, f"{safe_name}-webapp.zip"

    def download_directory(
        self, session_id: UUID, user_id: UUID, path: str
    ) -> tuple[bytes, str] | None:
        """Zip an arbitrary directory from the session workspace.
        Arcnames are relative to the requested directory."""
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        try:
            self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id, session_id=session_id, path=path
            )
        except ValueError:
            return None

        prefix_len = len(path) + 1
        files = _walk_sandbox_dir(
            self._sandbox_manager,
            sandbox.id,
            session_id,
            path,
            arcname_for=lambda p: p[prefix_len:],
        )
        zip_bytes = _zip_files(self._sandbox_manager, sandbox.id, session_id, files)

        dir_name = Path(path).name
        safe_name = _sanitize_zip_basename(dir_name, allow_dots=True)
        return zip_bytes, f"{safe_name}.zip"

    # =========================================================================
    # Workspace files
    # =========================================================================

    def list_directory(
        self, session_id: UUID, user_id: UUID, path: str
    ) -> DirectoryListing | None:
        """List a directory in the session workspace, directories first.

        Returns ``None`` only when the session or sandbox is missing
        (translated to 404). A missing workspace directory degrades to
        an empty listing so the file browser renders normally.

        Raises:
            ValueError: path-traversal attempt (e.g. ``../``).
        """
        resolved = self._resolve_owned_session_and_sandbox(session_id, user_id)
        if resolved is None:
            return None
        _, sandbox = resolved

        try:
            raw_entries = self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id, session_id=session_id, path=path
            )
        except ValueError as e:
            if "path traversal" in str(e).lower():
                raise
            return DirectoryListing(path=path, entries=[])

        entries: list[FileSystemEntry] = [
            entry
            for entry in raw_entries
            if entry.name not in _HIDDEN_FILESYSTEM_PATTERNS
            and not entry.name.startswith(".")
        ]
        entries.sort(key=lambda e: (not e.is_directory, e.name.lower()))
        return DirectoryListing(path=path, entries=entries)

    def get_upload_stats(self, session_id: UUID, user_id: UUID) -> tuple[int, int]:
        """``(file_count, total_size_bytes)`` for the session's uploads.
        Raises ``ValueError`` if session or sandbox is missing."""
        sandbox_id = self._require_session_and_sandbox(session_id, user_id)
        return self._sandbox_manager.get_upload_stats(
            sandbox_id=sandbox_id, session_id=session_id
        )

    def upload_file(
        self,
        session_id: UUID,
        user_id: UUID,
        filename: str,
        content: bytes,
    ) -> tuple[str, int]:
        """Save ``content`` into the session workspace.

        Returns the workspace-relative path and size. Filename
        sanitization is the caller's job (the API layer does it).

        Raises:
            ValueError: session/sandbox missing.
            UploadLimitExceededError: file count or total size cap hit.
        """
        sandbox_id = self._require_session_and_sandbox(session_id, user_id)
        file_count, total_size = self._sandbox_manager.get_upload_stats(
            sandbox_id=sandbox_id, session_id=session_id
        )
        if file_count >= MAX_UPLOAD_FILES_PER_SESSION:
            raise UploadLimitExceededError(
                f"Maximum number of files ({MAX_UPLOAD_FILES_PER_SESSION}) reached"
            )
        if total_size + len(content) > MAX_TOTAL_UPLOAD_SIZE_BYTES:
            max_mb = MAX_TOTAL_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise UploadLimitExceededError(
                f"Total upload size limit ({max_mb}MB) exceeded"
            )

        relative_path = self._sandbox_manager.upload_file(
            sandbox_id=sandbox_id,
            session_id=session_id,
            filename=filename,
            content=content,
        )
        update_sandbox_heartbeat(self._db_session, sandbox_id)
        return relative_path, len(content)

    def delete_file(self, session_id: UUID, user_id: UUID, path: str) -> bool:
        """Delete a file. Returns False if it didn't exist. Raises
        ``ValueError`` on missing session/sandbox or path traversal."""
        sandbox_id = self._require_session_and_sandbox(session_id, user_id)
        deleted = self._sandbox_manager.delete_file(
            sandbox_id=sandbox_id, session_id=session_id, path=path
        )
        if deleted:
            update_sandbox_heartbeat(self._db_session, sandbox_id)
        return deleted

    # =========================================================================
    # Shared persistence layer (used by scheduled-tasks executor + tests)
    #
    # These methods keep underscore prefixes for source-compatibility
    # but are part of an explicit contract: the headless executor
    # drives them directly so its persisted transcript is byte-
    # identical to an interactive run. Do not change signatures
    # without updating both ``scheduled_tasks/executor.py`` and the
    # streaming tests.
    # =========================================================================

    def _yield_sandbox_events(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        user_message_content: str,
        opencode_session_id: str | None = None,
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Generator[Any, None, None]:
        yield from _streaming.yield_sandbox_events(
            self._db_session,
            self._sandbox_manager,
            sandbox_id,
            session_id,
            user_message_content,
            opencode_session_id=opencode_session_id,
            should_interrupt=should_interrupt,
        )

    def _persist_sandbox_event(
        self,
        session_id: UUID,
        state: BuildStreamingState,
        sandbox_event: Any,
        routing_meta: dict[str, Any] | None = None,
    ) -> None:
        _streaming.persist_sandbox_event(
            self._db_session, session_id, state, sandbox_event, routing_meta
        )

    def _finalize_persist(
        self,
        session_id: UUID,
        state: BuildStreamingState,
        routing_meta: dict[str, Any] | None = None,
    ) -> None:
        _streaming.finalize_persist(self._db_session, session_id, state, routing_meta)

    # =========================================================================
    # Shared private helpers
    # =========================================================================

    def _fetch_user(self, user_id: UUID) -> User:
        user = fetch_user_by_id(self._db_session, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        return user

    def _resolve_owned_session_and_sandbox(
        self, session_id: UUID, user_id: UUID
    ) -> tuple[BuildSession, Sandbox] | None:
        """Verify ``user_id`` owns ``session_id`` AND has a sandbox
        row. Returns ``None`` so callers can 404 on either miss. Used
        by the read-mostly artifact + directory endpoints that prefer
        graceful degradation over raising."""
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None
        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            return None
        return session, sandbox

    def _require_session_and_sandbox(self, session_id: UUID, user_id: UUID) -> UUID:
        """Like :meth:`_resolve_owned_session_and_sandbox` but raises
        ``ValueError`` (translated to 4xx at the API layer) and returns
        only the sandbox id. Used by mutating endpoints (upload, delete,
        stats) where a missing sandbox is a hard failure."""
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise ValueError("Session not found")
        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            raise ValueError("Sandbox not found")
        return sandbox.id
