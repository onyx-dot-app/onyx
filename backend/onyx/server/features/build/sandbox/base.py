"""Abstract base class and factory for sandbox operations.

SandboxManager is the abstract interface for sandbox lifecycle management.
Use get_sandbox_manager() to get the appropriate implementation based on SANDBOX_BACKEND.

IMPORTANT: SandboxManager implementations must NOT interface with the database directly.
All database operations should be handled by the caller (SessionManager, Celery tasks, etc.).

Architecture Note (User-Shared Sandbox Model):
- One sandbox (container/pod) is shared across all of a user's sessions
- provision() creates the user's sandbox
- setup_session_workspace() creates per-session workspace within the sandbox
- cleanup_session_workspace() removes session workspace on session delete
- terminate() destroys the entire sandbox (all sessions)
"""

import contextlib
import os
import queue
import threading
import time
from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import httpx
from acp.schema import PromptResponse

from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import AGENT_TRANSPORT
from onyx.server.features.build.configs import AgentTransport
from onyx.server.features.build.configs import OPENCODE_SERVE_EVENT_READ_TIMEOUT
from onyx.server.features.build.configs import OPENCODE_SERVER_USERNAME
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import PushFailure
from onyx.server.features.build.sandbox.models import PushResult
from onyx.server.features.build.sandbox.models import RetriableWriteError
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.sandbox.opencode.event_bus import BUS_CLOSED_SENTINEL
from onyx.server.features.build.sandbox.opencode.event_bus import PodEventBus
from onyx.server.features.build.sandbox.opencode.serve_client import _TurnState
from onyx.server.features.build.sandbox.opencode.serve_client import OpencodeServeClient
from onyx.server.features.build.sandbox.opencode.serve_client import (
    translate_opencode_event,
)
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from onyx.utils.logger import setup_logger

# Re-export SSEKeepalive so existing ``from ...sandbox.base import
# SSEKeepalive`` callers keep working after the move into sse.py.
__all__ = ["SSEKeepalive"]

logger = setup_logger()


# In-sandbox paths shared by every backend implementation. Kept in sync with
# the SESSIONS_ROOT constants the individual managers define (those exist
# separately because the K8s manager emits exec scripts and the Docker
# manager mounts via the named volume — both happen to land at the same
# in-container path). The daemon's sandbox_daemon/snapshot.py also has its
# own copy because it can't import from this package at runtime.
BUN_CACHE_DIR = "/workspace/sessions/.bun-cache"
BUN_IMAGE_CACHE_DIR = "/home/sandbox/.bun/install/cache"

# ACPEvent is a union type defined in both local and kubernetes modules
# Using Any here to avoid circular imports - the actual type checking
# happens in the implementation modules
ACPEvent = Any

# Hostname of the api_server process — surfaces in serve-transport logs so
# operators can tell which replica is driving a given prompt. Pod name in
# K8s, container short-ID in Docker, "unknown" outside containers.
_API_SERVER_HOSTNAME = os.environ.get("HOSTNAME", "unknown")

# After the sandbox backend (pod/container) reports Ready, opencode-serve
# still has to finish its own boot (config parse, provider registry init,
# HTTP server bind on :4096). Empirically 1–3s warm, up to ~15s cold.
# Budget 30s so a slow boot fails loudly here instead of as a downstream
# "stream did not become ready".
OPENCODE_SERVE_READY_TIMEOUT_SECONDS = 30
OPENCODE_SERVE_READY_POLL_INTERVAL_SECONDS = 0.5


class SandboxManager(ABC):
    """Abstract interface for sandbox operations.

    Defines the contract for sandbox lifecycle management including:
    - Provisioning and termination (user-level)
    - Session workspace setup and cleanup (session-level)
    - Snapshot creation (session-level)
    - Health checks
    - Agent communication (session-level)
    - Filesystem operations (session-level)

    Directory Structure:
        $SANDBOX_ROOT/
        ├── managed/skills/            # Pushed skills, symlinked per session
        └── sessions/
            ├── $session_id_1/         # Per-session workspace
            │   ├── outputs/           # Agent output for this session
            │   │   └── web/           # Next.js app
            │   ├── venv/              # Python virtual environment
            │   ├── .opencode/skills   # Symlink → managed/skills
            │   ├── AGENTS.md          # Agent instructions
            │   ├── opencode.json      # LLM config
            │   └── attachments/
            └── $session_id_2/
                └── ...

    IMPORTANT: Implementations must NOT interface with the database directly.
    All database operations should be handled by the caller.

    Use get_sandbox_manager() to get the appropriate implementation.
    """

    @abstractmethod
    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        llm_config: LLMProviderConfig,
        onyx_pat: str | None = None,
        *,
        all_llm_configs: list[LLMProviderConfig] | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox for a user.

        ``all_llm_configs`` (serve transport only): the full set of LLM
        providers the user has configured. K8s pre-loads each into
        opencode-serve's startup config so per-prompt model overrides
        can cross providers without restarting the pod. Defaults to
        ``[llm_config]`` (single-provider, back-compat).

        Creates the sandbox container/directory with:
        - sessions/ directory for per-session workspaces

        NOTE: This does NOT set up session-specific workspaces.
        Call setup_session_workspace() after provisioning to create a session workspace.

        Args:
            sandbox_id: Unique identifier for the sandbox
            user_id: User identifier who owns this sandbox
            tenant_id: Tenant identifier for multi-tenant isolation
            llm_config: LLM provider configuration (for default config)
            onyx_pat: Raw PAT token to inject as ONYX_PAT env var in the sandbox

        Returns:
            SandboxInfo with the provisioned sandbox details

        Raises:
            RuntimeError: If provisioning fails
        """
        ...

    @abstractmethod
    def terminate(self, sandbox_id: UUID) -> None:
        """Terminate a sandbox and clean up all resources.

        Destroys the entire sandbox including all session workspaces.
        Use cleanup_session_workspace() to remove individual sessions.

        Args:
            sandbox_id: The sandbox ID to terminate
        """
        ...

    @abstractmethod
    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        skills_section: str,
        snapshot_path: str | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
    ) -> None:
        """Set up a session workspace within an existing sandbox.

        Creates the per-session directory structure:
        - sessions/$session_id/outputs/ (from snapshot or template)
        - sessions/$session_id/venv/
        - sessions/$session_id/.opencode/skills (symlink → managed skills dir)
        - sessions/$session_id/AGENTS.md
        - sessions/$session_id/opencode.json
        - sessions/$session_id/attachments/

        Args:
            sandbox_id: The sandbox ID (must be provisioned)
            session_id: The session ID for this workspace
            llm_config: LLM provider configuration for opencode.json
            nextjs_port: Port for the Next.js dev server, or None for headless.
            skills_section: Pre-rendered ``{{AVAILABLE_SKILLS_SECTION}}`` for AGENTS.md.
            snapshot_path: Optional storage path to restore outputs from
            user_name: User's name for personalization in AGENTS.md
            user_role: User's role/title for personalization in AGENTS.md

        Raises:
            RuntimeError: If workspace setup fails
        """
        ...

    @abstractmethod
    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        nextjs_port: int | None = None,
    ) -> None:
        """Clean up a session workspace (on session delete).

        1. Stop the Next.js dev server if running on nextjs_port
        2. Remove the session directory: sessions/$session_id/

        Does NOT terminate the sandbox - other sessions may still be using it.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to clean up
            nextjs_port: Optional port where Next.js server is running
        """
        ...

    @abstractmethod
    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        """Create a snapshot of a session's outputs and attachments directories.

        Captures session-specific user data:
        - sessions/$session_id/outputs/ (generated artifacts, web apps)
        - sessions/$session_id/attachments/ (user uploaded files)

        Does NOT include: venv, skills, AGENTS.md, opencode.json, files symlink
        (these are regenerated during restore)

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to snapshot
            tenant_id: Tenant identifier for storage path

        Returns:
            SnapshotResult with storage path and size, or None if:
            - Snapshots are disabled for this backend
            - No outputs directory exists (nothing to snapshot)

        Raises:
            RuntimeError: If snapshot creation fails
        """
        ...

    @abstractmethod
    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        tenant_id: str,
        nextjs_port: int | None,
        llm_config: LLMProviderConfig,
        skills_section: str,
    ) -> None:
        """Restore a session workspace from a snapshot.

        For Kubernetes: Downloads and extracts the snapshot, regenerates config files.
        For Local: No-op since workspaces persist on disk (no snapshots).

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to restore
            snapshot_storage_path: Path to the snapshot in storage
            tenant_id: Tenant identifier for storage access
            nextjs_port: Port number for the NextJS dev server, or None to
                skip starting it (e.g. headless scheduled-task fires).
            llm_config: LLM provider configuration for opencode.json

        Raises:
            RuntimeError: If snapshot restoration fails
        """
        ...

    @abstractmethod
    def session_workspace_exists(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> bool:
        """Check if a session's workspace directory exists in the sandbox.

        Used to determine if we need to restore from snapshot.
        Checks for sessions/$session_id/outputs/ directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to check

        Returns:
            True if the session workspace exists, False otherwise
        """
        ...

    @abstractmethod
    def list_session_workspaces(self, sandbox_id: UUID) -> list[UUID]:
        """List session workspace IDs under a sandbox's sessions/ directory.

        Used by idle cleanup to discover which sessions need snapshotting before
        the sandbox is terminated. Implementations should filter out non-UUID
        directory names.

        Args:
            sandbox_id: The sandbox ID

        Returns:
            List of session UUIDs found under sessions/. Returns an empty list
            if the sandbox is not running, has no sessions, or the backend does
            not support cleanup (e.g. local).
        """
        ...

    @abstractmethod
    def health_check(self, sandbox_id: UUID, timeout: float = 60.0) -> bool:
        """Check if the sandbox is healthy.

        Args:
            sandbox_id: The sandbox ID to check

        Returns:
            True if sandbox is healthy, False otherwise
        """
        ...

    @abstractmethod
    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
        *,
        opencode_session_id: str | None = None,
        agent_provider: str | None = None,
        agent_model: str | None = None,
        on_opencode_session_resolved: Callable[[str], None] | None = None,
    ) -> Generator[ACPEvent, None, None]:
        """Stream typed ACP events for one user message.

        Serve-only kwargs (ignored by ACP transport):

        - ``opencode_session_id``: persistent opencode-serve session id.
          Callers should pass ``BuildSession.opencode_session_id``; if
          ``None`` the transport calls :meth:`ensure_opencode_session`.
        - ``agent_provider`` / ``agent_model``: per-prompt model
          override (``body["model"]``). Both must be set; either
          ``None`` falls back to opencode's loaded default.
        - ``on_opencode_session_resolved``: invoked synchronously, before
          the first event is yielded, with the resolved opencode session
          id whenever it differs from the caller-supplied
          ``opencode_session_id`` (i.e. the persisted id 404'd and the
          transport had to mint a new one, or the caller passed ``None``).
          Callers persist the new id so subsequent turns don't 404 the
          same stale id and orphan a fresh opencode session per turn.
        """
        ...

    @contextlib.contextmanager
    def prompt_slot(
        self,
        sandbox_id: UUID,
        build_session_id: UUID,
    ) -> Generator[bool, None, None]:
        """Non-blocking try-acquire of a per-(sandbox, build_session) lock
        that serializes concurrent ``send_message`` calls on a build session.

        Yields ``True`` if the slot was acquired and the caller may proceed
        with the turn (lock is released on context exit), or ``False`` if a
        turn is already in flight on this build session and the caller
        should abort without side effects (no user_message persistence, no
        prompt POST).

        Why this exists: opencode-serve's ``prompt_async`` is fire-and-
        forget and not concurrent-safe — empirically, a second POST while
        a turn is in flight is silently dropped (no 409, no queue), and
        the second subscriber catches the *first* turn's terminator. Without
        serialization at this layer the user sees an empty response and a
        phantom user_message is persisted with no assistant reply.

        Keying on ``build_session_id`` (rather than ``opencode_session_id``)
        is deliberate:
          1. It's stable across opencode session id rotations triggered by
             the ``on_opencode_session_resolved`` callback — concurrent
             requests landing in the middle of a 404-then-mint sequence
             still contend on the same lock.
          2. It blocks first-turn races: two simultaneous prompts on a
             fresh build session (where ``opencode_session_id`` is NULL
             for both) both contend before each calls POST /session, so
             only one opencode session is ever created.
          3. It bounds the lock dict size to one entry per build session
             instead of one per (build_session × pod_restart_count).

        Under ``AGENT_TRANSPORT=acp`` (rollback path) this is a no-op
        (yields ``True``) — the per-message exec'd ``opencode acp``
        subprocess model has no shared state to serialize.
        """
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            yield True
            return

        key = (sandbox_id, build_session_id)
        with self._prompt_locks_meta:
            lock = self._prompt_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._prompt_locks[key] = lock

        acquired = lock.acquire(blocking=False)
        try:
            if not acquired:
                logger.warning(
                    "[SANDBOX-SERVE] prompt_slot: refused — concurrent send_message "
                    "on sandbox=%s build_session=%s",
                    sandbox_id,
                    build_session_id,
                )
            yield acquired
        finally:
            if acquired:
                lock.release()

    def ensure_opencode_session(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> str | None:
        """Return a stable opencode-serve session id for this build session.

        Used only when ``AGENT_TRANSPORT=serve``. The caller (session
        manager) persists the returned id on the ``BuildSession`` row so
        subsequent ``send_message`` calls can hit the same opencode
        session by id, eliminating the on-disk session/list heuristic
        the ACP path uses.

        Returns ``None`` under ACP — that transport has no notion of a
        persistent session id and doesn't need this preflight.

        Idempotent: calling twice for the same (sandbox, session) on serve
        returns the same id (delegated to ``OpencodeServeClient.ensure_session``).
        """
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            return None
        session_path = f"/workspace/sessions/{session_id}"
        logger.info(
            "[SESSION-LIFECYCLE] sandbox.ensure_opencode_session: build_session=%s "
            "sandbox=%s cwd=%s (passing id=None, so client will POST /session)",
            session_id,
            sandbox_id,
            session_path,
        )
        with self._build_serve_client(sandbox_id) as client:
            return client.ensure_session(
                None,
                directory=session_path,
                title=f"build-session-{str(session_id)[:8]}",
            )

    def list_subagents(
        self,
        sandbox_id: UUID,
        parent_opencode_session_id: str,
    ) -> list[str]:
        """Child opencode session ids spawned under the parent. Empty
        under ACP (no shared event bus to track subagents)."""
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            return []
        # Don't create a bus just to list — that spins up a reader thread
        # for a caller that didn't ask for events.
        with self._event_buses_lock:
            bus = self._event_buses.get(sandbox_id)
        if bus is None:
            return []
        return bus.list_children(parent_opencode_session_id)

    def subscribe_to_opencode_session(
        self,
        sandbox_id: UUID,
        opencode_session_id: str,
        *,
        directory: str,
        keepalive_seconds: float = 15.0,
    ) -> Generator["ACPEvent", None, None]:
        """Stream translated ACP events for an opencode session (parent
        or child). Never terminates on its own; caller closes via
        ``GeneratorExit``. Empty under ACP.

        ``directory`` is the in-sandbox session path
        (``/workspace/sessions/{build_session_id}``) — opencode-serve
        scopes its session store per-directory, so the hydrate REST call
        needs it. Without it, the delta-before-``message.updated`` race
        falls back to the negative-cache path and drops in-flight
        deltas for the current step on subagent streams.
        """
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            return
        bus = self._get_or_create_event_bus(sandbox_id)
        state = _TurnState(session_id=opencode_session_id)
        client = self._build_serve_client(sandbox_id)

        def fetch_message(mid: str) -> dict[str, Any] | None:
            return client.get_message(opencode_session_id, mid, directory=directory)

        sub = bus.subscribe(opencode_session_id)
        try:
            last_event = time.monotonic()
            while True:
                try:
                    raw = sub.queue.get(timeout=1.0)
                except queue.Empty:
                    if time.monotonic() - last_event >= keepalive_seconds:
                        yield SSEKeepalive()
                        last_event = time.monotonic()
                    continue
                if raw is BUS_CLOSED_SENTINEL:
                    return
                last_event = time.monotonic()
                if raw.get("type") == "server.connected":
                    continue
                for acp_event in translate_opencode_event(
                    raw, state, fetch_message=fetch_message
                ):
                    yield acp_event
        finally:
            bus.unsubscribe(sub)
            client.close()

    # =====================================================================
    # opencode serve transport — shared plumbing
    # =====================================================================
    #
    # Subclasses provide the two backend-specific endpoints (`_serve_base_url`
    # and `_read_opencode_password`); the rest of the serve transport is
    # backend-agnostic and lives here.

    def _init_serve_state(self) -> None:
        """Initialize per-instance serve-transport state. Subclasses MUST
        call this from their ``_initialize`` before any serve-path method
        runs. Idempotent — guarded against double-init via attribute check.
        """
        if getattr(self, "_serve_state_initialized", False):
            return
        # One PodEventBus per sandbox, created lazily on first send_message.
        self._event_buses: dict[UUID, PodEventBus] = {}
        # Tombstone set: blocks late ``subscribe`` from re-creating a bus
        # for a sandbox whose terminate is in flight (leaks a reconnect
        # loop otherwise). Cleared on re-provision.
        self._terminated_sandboxes: set[UUID] = set()
        self._event_buses_lock = threading.Lock()
        # Per-(sandbox_id, build_session_id) locks that serialize concurrent
        # send_message calls on a single build session. See prompt_slot for
        # why we key on build_session_id rather than opencode_session_id.
        self._prompt_locks: dict[tuple[UUID, UUID], threading.Lock] = {}
        self._prompt_locks_meta: threading.Lock = threading.Lock()
        self._serve_state_initialized = True

    @abstractmethod
    def _serve_base_url(self, sandbox_id: UUID) -> str:
        """Backend-specific base URL for this sandbox's opencode-serve.

        K8s: per-pod ClusterIP service on the cluster DNS.
        Docker: container name on the sandbox bridge network.
        """
        ...

    @abstractmethod
    def _read_opencode_password(self, sandbox_id: UUID) -> str | None:
        """Backend-specific lookup of the per-sandbox HTTP Basic password.

        Returns ``None`` if the sandbox doesn't have one (e.g. legacy
        provisioned before this code landed). Callers should fall back
        to no-auth in that case.
        """
        ...

    def _wait_for_opencode_serve_ready(
        self,
        sandbox_id: UUID,
        timeout: float = OPENCODE_SERVE_READY_TIMEOUT_SECONDS,
    ) -> bool:
        """Block until opencode-serve answers ``GET /doc`` with 200.

        Backend readiness (k8s pod Ready / docker container running) only
        proves the supervisor process is up. opencode-serve binds ``:4096``
        a few hundred ms to a few seconds later, after it finishes config
        parse and provider registry init. Returning RUNNING before that
        means the first prompt's bus subscribe races a cold opencode —
        connection refused or stale-auth 401 burns the bus's reconnect
        budget and surfaces to the user as ``stream did not become ready``.

        No-op under AGENT_TRANSPORT=acp.
        """
        if AGENT_TRANSPORT != AgentTransport.SERVE:
            return True

        password = self._read_opencode_password(sandbox_id)
        auth = httpx.BasicAuth(OPENCODE_SERVER_USERNAME, password) if password else None
        base_url = self._serve_base_url(sandbox_id)
        deadline = time.time() + timeout
        last_err: str | None = None
        while time.time() < deadline:
            try:
                with httpx.Client(base_url=base_url, auth=auth, timeout=2.0) as client:
                    r = client.get("/doc")
                    if r.status_code == 200:
                        logger.info(
                            "[SANDBOX-SERVE] opencode-serve ready for sandbox %s",
                            sandbox_id,
                        )
                        return True
                    last_err = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last_err = f"{type(e).__name__}: {e}"
            time.sleep(OPENCODE_SERVE_READY_POLL_INTERVAL_SECONDS)
        logger.error(
            "[SANDBOX-SERVE] opencode-serve never became ready for sandbox %s "
            "after %.0fs (last error: %s)",
            sandbox_id,
            timeout,
            last_err,
        )
        return False

    def _get_or_create_event_bus(self, sandbox_id: UUID) -> PodEventBus:
        """Lazily build the per-sandbox :class:`PodEventBus`. Refuses to
        create one for a terminated sandbox (see ``_terminated_sandboxes``).

        Replaces a cached bus that has self-closed (exhausted its reconnect
        budget) with a fresh one — otherwise callers would keep getting
        ``BUS_CLOSED_SENTINEL`` until the api server restarted.
        """
        with self._event_buses_lock:
            bus = self._event_buses.get(sandbox_id)
            if bus is not None and not bus.closed:
                return bus
            if bus is not None and bus.closed:
                logger.warning(
                    "[SANDBOX-SERVE] Replacing self-closed PodEventBus for "
                    "sandbox %s (prior bus exhausted its reconnect budget)",
                    sandbox_id,
                )
                self._event_buses.pop(sandbox_id, None)
            if sandbox_id in self._terminated_sandboxes:
                raise RuntimeError(
                    f"Sandbox {sandbox_id} has been terminated; refusing to "
                    "create a new event bus against its (deleted) backend"
                )
            password = self._read_opencode_password(sandbox_id)
            if password is None:
                logger.warning(
                    "[SANDBOX-SERVE] No opencode password for sandbox %s; "
                    "bus will run without auth (likely a legacy sandbox, re-provision to fix)",
                    sandbox_id,
                )
            auth = (
                httpx.BasicAuth(OPENCODE_SERVER_USERNAME, password)
                if password
                else None
            )
            bus = PodEventBus(
                base_url=self._serve_base_url(sandbox_id),
                auth=auth,
                event_read_timeout=OPENCODE_SERVE_EVENT_READ_TIMEOUT,
            )
            self._event_buses[sandbox_id] = bus
            logger.info(
                "[SANDBOX-SERVE] Created PodEventBus for sandbox %s", sandbox_id
            )
            return bus

    def _build_serve_client(self, sandbox_id: UUID) -> OpencodeServeClient:
        password = self._read_opencode_password(sandbox_id)
        bus = self._get_or_create_event_bus(sandbox_id)
        return OpencodeServeClient(
            base_url=self._serve_base_url(sandbox_id),
            password=password,
            event_bus=bus,
        )

    def _send_message_via_serve(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
        opencode_session_id: str | None,
        agent_provider: str | None,
        agent_model: str | None,
        *,
        on_opencode_session_resolved: Callable[[str], None] | None = None,
    ) -> Generator["ACPEvent", None, None]:
        """Stream ACP events by driving the in-sandbox ``opencode serve`` via
        :class:`OpencodeServeClient`. See
        ``docs/craft/opencode-serve-migration.md``.

        ``opencode_session_id`` is the caller-persisted id from
        ``BuildSession.opencode_session_id``. If ``None``, fall back to
        creating one inline — but the session manager *should* preflight
        via :meth:`ensure_opencode_session` and persist before calling
        here, to avoid creating a fresh opencode session per turn under
        a race.
        """
        packet_logger = get_packet_logger()
        session_path = f"/workspace/sessions/{session_id}"
        client = self._build_serve_client(sandbox_id)
        try:
            logger.info(
                "[SESSION-LIFECYCLE] _send_message_via_serve: build_session=%s "
                "caller-supplied opencode_session_id=%s",
                session_id,
                opencode_session_id,
            )
            resolved_session_id = client.ensure_session(
                opencode_session_id,
                directory=session_path,
                title=f"build-session-{str(session_id)[:8]}",
            )
            if resolved_session_id != opencode_session_id:
                # Caller's persisted id was stale (404) or missing. Notify
                # the caller so they can persist the new id; without this,
                # _ensure_opencode_session_id would reload the same stale
                # id from the DB on every turn, 404 again, and orphan a
                # fresh opencode session per turn (one assistant message
                # per orphan → conversation loses all prior context).
                if opencode_session_id is not None:
                    logger.warning(
                        "[SANDBOX-SERVE] persisted opencode_session_id %s was "
                        "invalid; replaced with %s for session=%s",
                        opencode_session_id,
                        resolved_session_id,
                        session_id,
                    )
                if on_opencode_session_resolved is not None:
                    on_opencode_session_resolved(resolved_session_id)

            logger.info(
                "[SANDBOX-SERVE] Sending message: session=%s opencode_session=%s api_pod=%s",
                session_id,
                resolved_session_id,
                _API_SERVER_HOSTNAME,
            )
            packet_logger.log_session_start(session_id, sandbox_id, message)

            events_count = 0
            got_prompt_response = False
            try:
                for event in client.send_message(
                    resolved_session_id,
                    message,
                    directory=session_path,
                    model_provider=agent_provider,
                    model_id=agent_model,
                ):
                    events_count += 1
                    if isinstance(event, PromptResponse):
                        got_prompt_response = True
                    yield event

                logger.info(
                    "[SANDBOX-SERVE] send_message completed: session=%s events=%s got_prompt_response=%s",
                    session_id,
                    events_count,
                    got_prompt_response,
                )
                packet_logger.log_session_end(
                    session_id, success=True, events_count=events_count
                )
            except GeneratorExit:
                logger.warning(
                    "[SANDBOX-SERVE] GeneratorExit: session=%s events=%s, sending abort",
                    session_id,
                    events_count,
                )
                try:
                    client.abort(resolved_session_id, directory=session_path)
                except Exception as abort_err:
                    logger.warning(
                        "[SANDBOX-SERVE] abort failed on GeneratorExit: %s",
                        abort_err,
                    )
                packet_logger.log_session_end(
                    session_id,
                    success=False,
                    error="GeneratorExit",
                    events_count=events_count,
                )
                raise
            except Exception as e:
                logger.error(
                    "[SANDBOX-SERVE] Exception: session=%s events=%s error=%s",
                    session_id,
                    events_count,
                    e,
                )
                try:
                    client.abort(resolved_session_id, directory=session_path)
                except Exception as abort_err:
                    logger.warning(
                        "[SANDBOX-SERVE] abort failed on Exception: %s",
                        abort_err,
                    )
                packet_logger.log_session_end(
                    session_id,
                    success=False,
                    error=f"Exception: {e}",
                    events_count=events_count,
                )
                raise
        finally:
            client.close()

    @abstractmethod
    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        """List contents of a directory in the session's outputs directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path within sessions/$session_id/outputs/

        Returns:
            List of FilesystemEntry objects sorted by directory first, then name

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        ...

    @abstractmethod
    def read_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bytes:
        """Read a file from the session's workspace.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path within sessions/$session_id/

        Returns:
            File contents as bytes

        Raises:
            ValueError: If path traversal attempted or path is not a file
        """
        ...

    @abstractmethod
    def upload_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        """Upload a file to the session's attachments directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            filename: Sanitized filename
            content: File content as bytes

        Returns:
            Relative path where file was saved (e.g., "attachments/doc.pdf")

        Raises:
            RuntimeError: If upload fails
        """
        ...

    @abstractmethod
    def delete_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        path: str,
    ) -> bool:
        """Delete a file from the session's workspace.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path to the file (e.g., "attachments/doc.pdf")

        Returns:
            True if file was deleted, False if not found

        Raises:
            ValueError: If path traversal attempted
        """
        ...

    @abstractmethod
    def write_sandbox_file(
        self,
        sandbox_id: UUID,
        path: str,
        content: str,
    ) -> None:
        """Write a text file to the sandbox workspace root.

        Creates parent directories as needed. Sessions symlink to the
        sandbox-root skills directory, so writes here are visible to
        all sessions.

        Args:
            sandbox_id: The sandbox ID
            path: Relative path (e.g., "skills/company-search/SKILL.md").
                Must not contain ".." or start with "/".
            content: UTF-8 text content to write

        Raises:
            RuntimeError: If write fails
            ValueError: If path is invalid
        """
        ...

    @abstractmethod
    def get_upload_stats(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> tuple[int, int]:
        """Get current file count and total size for a session's attachments.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID

        Returns:
            Tuple of (file_count, total_size_bytes)
        """
        ...

    @abstractmethod
    def write_files_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
    ) -> None:
        """Write files atomically to a sandbox. Raise RetriableWriteError for
        transients, FatalWriteError for permanent failures."""
        ...

    def push_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
        timeout_s: float = 30.0,
    ) -> PushResult:
        """Push files to a single sandbox with retry."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.write_files_to_sandbox(
                    sandbox_id=sandbox_id,
                    mount_path=mount_path,
                    files=files,
                )
                return PushResult(targets=1, succeeded=1, failures=[])
            except FatalWriteError as e:
                return PushResult(
                    targets=1,
                    succeeded=0,
                    failures=[
                        PushFailure(
                            sandbox_id=sandbox_id,
                            reason="write_error",
                            detail=str(e),
                        )
                    ],
                )
            except RetriableWriteError:
                if attempt < max_retries - 1:
                    time.sleep(min(2**attempt, timeout_s / max_retries))
                    continue
                return PushResult(
                    targets=1,
                    succeeded=0,
                    failures=[
                        PushFailure(
                            sandbox_id=sandbox_id,
                            reason="timeout",
                            detail=f"Failed after {max_retries} retries",
                        )
                    ],
                )
            except Exception as e:
                logger.warning(
                    "Unexpected error pushing to sandbox %s: %s",
                    sandbox_id,
                    e,
                )
                return PushResult(
                    targets=1,
                    succeeded=0,
                    failures=[
                        PushFailure(
                            sandbox_id=sandbox_id,
                            reason="write_error",
                            detail=str(e),
                        )
                    ],
                )
        raise AssertionError("unreachable: all retries should return")

    def push_to_sandboxes(
        self,
        *,
        mount_path: str,
        sandbox_files: dict[UUID, FileSet],
        timeout_s: float = 30.0,
    ) -> PushResult:
        """Push files to multiple sandboxes in parallel.

        Caller owns user→sandbox resolution (via DB). This method only handles
        parallelism and result aggregation over push_to_sandbox.
        """
        if not sandbox_files:
            return PushResult(targets=0, succeeded=0, failures=[])

        all_failures: list[PushFailure] = []
        pushed = 0

        def _push_one(sandbox_id: UUID) -> PushResult:
            return self.push_to_sandbox(
                sandbox_id=sandbox_id,
                mount_path=mount_path,
                files=sandbox_files[sandbox_id],
                timeout_s=timeout_s,
            )

        with ThreadPoolExecutor(max_workers=min(len(sandbox_files), 10)) as pool:
            for result in pool.map(_push_one, sandbox_files):
                pushed += result.succeeded
                all_failures.extend(result.failures)

        if all_failures:
            logger.warning(
                "push_to_sandboxes: %d/%d targets failed for mount_path=%s",
                len(all_failures),
                len(sandbox_files),
                mount_path,
            )

        return PushResult(
            targets=len(sandbox_files),
            succeeded=pushed,
            failures=all_failures,
        )

    @abstractmethod
    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        """Get the webapp URL for a session's Next.js server.

        Returns the appropriate URL based on the backend:
        - Local: Returns localhost URL with port
        - Kubernetes: Returns internal cluster service URL

        Args:
            sandbox_id: The sandbox ID
            port: The session's allocated Next.js port

        Returns:
            URL to access the webapp
        """
        ...

    @abstractmethod
    def generate_pptx_preview(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        pptx_path: str,
        cache_dir: str,
    ) -> tuple[list[str], bool]:
        """Convert PPTX to slide JPEG images for preview, with caching.

        Checks if cache_dir already has slides. If the PPTX is newer than the
        cached images (or no cache exists), runs soffice -> pdftoppm pipeline.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            pptx_path: Relative path to the PPTX file within the session workspace
            cache_dir: Relative path for the cache directory
                       (e.g., "outputs/.pptx-preview/abc123")

        Returns:
            Tuple of (slide_paths, cached) where slide_paths is a list of
            relative paths to slide JPEG images (within session workspace)
            and cached indicates whether the result was served from cache.

        Raises:
            ValueError: If file not found or conversion fails
        """
        ...

    def ensure_nextjs_running(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        nextjs_port: int,
    ) -> None:
        """Ensure the Next.js server is running for a session.

        Default is a no-op — only meaningful for backends that manage Next.js
        process lifecycles directly from the api_server side. The kubernetes
        backend starts Next.js inside the sandbox pod at workspace setup, so
        nothing further is needed.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            nextjs_port: The port the Next.js server should be listening on
        """


# Singleton instance cache for the factory
_sandbox_manager_instance: SandboxManager | None = None
_sandbox_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    """Get the appropriate SandboxManager implementation based on SANDBOX_BACKEND.

    Returns:
        SandboxManager instance:
        - KubernetesSandboxManager for kubernetes backend (production + dev kind)
        - DockerSandboxManager for self-hosted docker-compose
    """
    global _sandbox_manager_instance

    if _sandbox_manager_instance is None:
        with _sandbox_manager_lock:
            if _sandbox_manager_instance is None:
                if SANDBOX_BACKEND == SandboxBackend.KUBERNETES:
                    from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
                        KubernetesSandboxManager,
                    )

                    _sandbox_manager_instance = KubernetesSandboxManager()
                    logger.info("Using KubernetesSandboxManager for sandbox operations")
                elif SANDBOX_BACKEND == SandboxBackend.DOCKER:
                    from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
                        DockerSandboxManager,
                    )

                    _sandbox_manager_instance = DockerSandboxManager()
                    logger.info("Using DockerSandboxManager for sandbox operations")
                else:
                    raise ValueError(f"Unknown sandbox backend: {SANDBOX_BACKEND}")

    return _sandbox_manager_instance
