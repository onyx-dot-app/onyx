"""Test-double sandbox manager for craft tests.

This module exposes ``StubSandboxManager`` — a controllable, in-memory
implementation of ``SandboxManager``. It is intentionally **strict**: any
abstract method on the ABC that is invoked without explicit configuration on
the stub raises ``NotImplementedError`` with a message naming the method.

Rationale
---------
1. **Forces tests to declare their surface.** Each test states which slice of
   the manager it exercises by setting an attribute (e.g.
   ``stub.provision_returns``) or by opting a method into "silent no-op" mode
   (``stub.terminate_silent = True``). Anything else raises loudly, so the
   test cannot accidentally pass by virtue of a stub silently returning
   ``None``/empty.
2. **Surfaces ABC drift.** When ``SandboxManager`` gains a new abstract
   method, every consuming test fails until it opts in or out. That is the
   point: a new abstract method is a new contract the tests must reckon with.
3. **Enables fault injection.** Several attributes
   (``write_files_to_sandbox_raises_for``, ``send_message_events``, ...) let
   tests inject the rare-but-load-bearing failures (RetriableWriteError,
   FatalWriteError, sandbox event sequences) without reaching for ``MagicMock``.

Observable state (P1: assert behaviour, not implementation)
----------------------------------------------------------
Instead of a free-form call log, the stub exposes scoped counters and last-
payload snapshots so tests assert observable manager outcomes:

- ``provision_count``, ``terminate_count``, ``setup_session_workspace_count``,
  ``cleanup_session_workspace_count``, ``restore_snapshot_count``,
  ``send_message_count``, ``write_sandbox_file_count``,
  ``write_files_to_sandbox_count``.
- ``last_provision_payload``, ``last_terminate_sandbox_id``,
  ``last_setup_session_workspace_payload``,
  ``last_cleanup_session_workspace_payload``,
  ``last_restore_snapshot_payload``, ``last_send_message_payload``,
  ``last_write_sandbox_file_payload``, ``last_write_files_to_sandbox_payload``.

Usage
-----
::

    stub = StubSandboxManager()
    stub.send_message_events = [AgentMessageChunk(...), PromptResponse(...)]
    list(stub.send_message(sandbox_id, session_id, "hi"))
    assert stub.send_message_count == 1
    assert stub.last_send_message_payload["message"] == "hi"
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from typing import Any
from typing import cast
from uuid import UUID

from onyx.server.features.build.sandbox.base import SandboxEvent
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.sandbox.serve_transport import ServeConnectionInfo

_UNSET = object()


def _not_configured(method_name: str) -> NotImplementedError:
    return NotImplementedError(
        f"StubSandboxManager.{method_name} not configured for this test — "
        "set the corresponding attribute or override the method."
    )


class StubSandboxManager(SandboxManager):
    """Controllable test double for ``SandboxManager``.

    Unconfigured methods raise ``NotImplementedError``. Configure behaviour
    by setting attributes on an instance:

    Return-value hooks
    ------------------
    - ``provision_returns``: ``SandboxInfo`` returned by ``provision``.
    - ``health_check_returns``: bool returned by ``health_check``.
    - ``session_workspace_exists_returns``: bool returned by
      ``session_workspace_exists``.
    - ``send_message_events``: iterable of sandbox events yielded by
      ``send_message``. The iterable is **snapshotted to a list on
      assignment** so the same stub can be re-driven across multiple
      ``send_message`` calls.
    - ``subscribe_to_opencode_session_events``: iterable of ACP events yielded
      by ``subscribe_to_opencode_session``.
    - ``create_snapshot_returns``: ``SnapshotResult | None`` returned by
      ``create_snapshot``.
    - ``list_directory_returns``, ``read_file_returns``,
      ``upload_file_returns``, ``delete_file_returns``,
      ``get_upload_stats_returns``, ``get_webapp_url_returns``,
      ``generate_pptx_preview_returns``: return values for the matching
      filesystem / utility methods.

    Silent no-op opt-ins
    --------------------
    Methods with no meaningful return value still raise by default. Tests
    that want them to no-op set the corresponding ``*_silent`` flag:

    - ``terminate_silent``
    - ``setup_session_workspace_silent``
    - ``cleanup_session_workspace_silent``
    - ``restore_snapshot_silent``
    - ``write_sandbox_file_silent``
    - ``write_files_to_sandbox_silent``

    Fault injection
    ---------------
    - ``write_files_to_sandbox_raises_for``: ``dict[UUID, Exception]``
      mapping sandbox IDs to exceptions raised on ``write_files_to_sandbox``.
      A non-empty mapping implies the method is configured even without
      ``write_files_to_sandbox_silent``; sandboxes not present in the map
      succeed silently.
    """

    def __init__(self) -> None:
        # Tests hitting prompt_slot / list_subagents need the mixin state.
        self._init_serve_state()

        # Return-value hooks.
        self.provision_returns: SandboxInfo | None = None
        self.health_check_returns: bool | None = None
        self.session_workspace_exists_returns: bool | None = None
        self.create_snapshot_returns: SnapshotResult | None | object = _UNSET
        self.create_opencode_history_snapshot_returns: bool | object = _UNSET
        self.list_directory_returns: list[FilesystemEntry] | None = None
        self.read_file_returns: bytes | None = None
        self.upload_file_returns: str | None = None
        self.delete_file_returns: bool | None = None
        self.delete_opencode_session_returns: bool | Exception = True
        self.prompt_slot_returns: bool = True
        self.get_upload_stats_returns: tuple[int, int] | None = None
        self.get_webapp_url_returns: str | None = None
        self.generate_pptx_preview_returns: tuple[list[str], bool] | None = None
        # Preflight session id. Defaulted (not _not_configured) so send_message
        # tests don't each have to wire it; the real _ServeMixin override POSTs
        # /session over HTTP, which has no pod to reach under the stub.
        self.ensure_opencode_session_returns: str | None = "stub-opencode-session"

        # Silent no-op opt-ins for methods that legitimately return None.
        self.terminate_silent: bool = False
        self.setup_session_workspace_silent: bool = False
        self.cleanup_session_workspace_silent: bool = False
        self.restore_snapshot_silent: bool = False
        self.write_sandbox_file_silent: bool = False
        self.write_files_to_sandbox_silent: bool = False

        # Fault injection.
        self.write_files_to_sandbox_raises_for: dict[UUID, Exception] | None = None

        # ``send_message_events`` is stored via the property below so it is
        # materialised at assignment time (see __setattr__-like setter).
        self._send_message_events: list[SandboxEvent] | None = None
        self._subscribe_to_opencode_session_events: list[SandboxEvent] | None = None

        # Observable state: scoped counters and last-payload snapshots.
        self.provision_count: int = 0
        self.terminate_count: int = 0
        self.terminated_sandbox_ids: list[UUID] = []
        self.setup_session_workspace_count: int = 0
        self.cleanup_session_workspace_count: int = 0
        self.create_snapshot_count: int = 0
        self.create_opencode_history_snapshot_count: int = 0
        self.restore_snapshot_count: int = 0
        self.session_workspace_exists_count: int = 0
        self.list_session_workspaces_count: int = 0
        self.list_session_workspaces_returns: list[UUID] | None = None
        self.list_session_workspaces_payloads: list[dict[str, Any]] = []
        self.last_list_session_workspaces_payload: dict[str, Any] | None = None
        self.health_check_count: int = 0
        self.ensure_opencode_session_count: int = 0
        self.last_ensure_opencode_session_payload: dict[str, Any] | None = None
        self.send_message_count: int = 0
        self.subscribe_to_opencode_session_count: int = 0
        self.list_directory_count: int = 0
        self.read_file_count: int = 0
        self.upload_file_count: int = 0
        self.delete_file_count: int = 0
        self.delete_opencode_session_count: int = 0
        self.prompt_slot_count: int = 0
        self.write_sandbox_file_count: int = 0
        self.get_upload_stats_count: int = 0
        self.write_files_to_sandbox_count: int = 0
        self.get_webapp_url_count: int = 0
        self.generate_pptx_preview_count: int = 0

        self.last_provision_payload: dict[str, Any] | None = None
        self.last_terminate_sandbox_id: UUID | None = None
        self.last_setup_session_workspace_payload: dict[str, Any] | None = None
        self.last_cleanup_session_workspace_payload: dict[str, Any] | None = None
        self.last_create_snapshot_payload: dict[str, Any] | None = None
        self.last_create_opencode_history_snapshot_payload: dict[str, Any] | None = None
        self.create_opencode_history_snapshot_payloads: list[dict[str, Any]] = []
        self.last_restore_snapshot_payload: dict[str, Any] | None = None
        self.last_session_workspace_exists_payload: dict[str, Any] | None = None
        self.last_health_check_payload: dict[str, Any] | None = None
        self.last_send_message_payload: dict[str, Any] | None = None
        self.last_subscribe_to_opencode_session_payload: dict[str, Any] | None = None
        self.last_list_directory_payload: dict[str, Any] | None = None
        self.last_read_file_payload: dict[str, Any] | None = None
        self.last_upload_file_payload: dict[str, Any] | None = None
        self.last_delete_file_payload: dict[str, Any] | None = None
        self.last_delete_opencode_session_payload: dict[str, Any] | None = None
        self.last_prompt_slot_payload: dict[str, Any] | None = None
        self.last_write_sandbox_file_payload: dict[str, Any] | None = None
        self.last_get_upload_stats_payload: dict[str, Any] | None = None
        self.last_write_files_to_sandbox_payload: dict[str, Any] | None = None
        self.last_get_webapp_url_payload: dict[str, Any] | None = None
        self.last_generate_pptx_preview_payload: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # send_message_events property: snapshot iterables on assignment so
    # each call to ``send_message`` yields a fresh iterator over the same
    # underlying sequence.
    # ------------------------------------------------------------------

    @property
    def send_message_events(self) -> list[SandboxEvent] | None:
        return self._send_message_events

    @send_message_events.setter
    def send_message_events(self, value: Iterable[SandboxEvent] | None) -> None:
        self._send_message_events = None if value is None else list(value)

    @property
    def subscribe_to_opencode_session_events(self) -> list[SandboxEvent] | None:
        return self._subscribe_to_opencode_session_events

    @subscribe_to_opencode_session_events.setter
    def subscribe_to_opencode_session_events(
        self, value: Iterable[SandboxEvent] | None
    ) -> None:
        self._subscribe_to_opencode_session_events = (
            None if value is None else list(value)
        )

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
        self.provision_count += 1
        self.last_provision_payload = {
            "sandbox_id": sandbox_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "llm_config": llm_config,
            "onyx_pat": onyx_pat,
            "all_llm_configs": all_llm_configs,
        }
        if self.provision_returns is None:
            raise _not_configured("provision")
        return self.provision_returns

    def terminate(self, sandbox_id: UUID) -> None:
        self.terminate_count += 1
        self.last_terminate_sandbox_id = sandbox_id
        self.terminated_sandbox_ids.append(sandbox_id)
        if not self.terminate_silent:
            raise _not_configured("terminate")

    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        skills_section: str,
        user_name: str | None = None,
    ) -> None:
        self.setup_session_workspace_count += 1
        self.last_setup_session_workspace_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "llm_config": llm_config,
            "nextjs_port": nextjs_port,
            "skills_section": skills_section,
            "user_name": user_name,
        }
        if not self.setup_session_workspace_silent:
            raise _not_configured("setup_session_workspace")

    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> None:
        self.cleanup_session_workspace_count += 1
        self.last_cleanup_session_workspace_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
        }
        if not self.cleanup_session_workspace_silent:
            raise _not_configured("cleanup_session_workspace")

    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        self.create_snapshot_count += 1
        self.last_create_snapshot_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "tenant_id": tenant_id,
        }
        if self.create_snapshot_returns is _UNSET:
            raise _not_configured("create_snapshot")
        return cast("SnapshotResult | None", self.create_snapshot_returns)

    def create_opencode_history_snapshot(
        self,
        sandbox_id: UUID,
        tenant_id: str,
        timeout_seconds: float = 300.0,
    ) -> bool:
        self.create_opencode_history_snapshot_count += 1
        self.last_create_opencode_history_snapshot_payload = {
            "sandbox_id": sandbox_id,
            "tenant_id": tenant_id,
            "timeout_seconds": timeout_seconds,
        }
        self.create_opencode_history_snapshot_payloads.append(
            self.last_create_opencode_history_snapshot_payload
        )
        if self.create_opencode_history_snapshot_returns is _UNSET:
            raise _not_configured("create_opencode_history_snapshot")
        return cast(bool, self.create_opencode_history_snapshot_returns)

    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        nextjs_port: int | None,
        llm_config: LLMProviderConfig,
        skills_section: str,
    ) -> None:
        self.restore_snapshot_count += 1
        self.last_restore_snapshot_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "snapshot_storage_path": snapshot_storage_path,
            "nextjs_port": nextjs_port,
            "llm_config": llm_config,
            "skills_section": skills_section,
        }
        if not self.restore_snapshot_silent:
            raise _not_configured("restore_snapshot")

    def session_workspace_exists(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> bool:
        self.session_workspace_exists_count += 1
        self.last_session_workspace_exists_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
        }
        if self.session_workspace_exists_returns is None:
            raise _not_configured("session_workspace_exists")
        return self.session_workspace_exists_returns

    def list_session_workspaces(self, sandbox_id: UUID) -> list[UUID]:
        self.list_session_workspaces_count += 1
        self.last_list_session_workspaces_payload = {"sandbox_id": sandbox_id}
        self.list_session_workspaces_payloads.append(
            self.last_list_session_workspaces_payload
        )
        if self.list_session_workspaces_returns is None:
            raise _not_configured("list_session_workspaces")
        return list(self.list_session_workspaces_returns)

    def health_check(self, sandbox_id: UUID, timeout: float = 60.0) -> bool:
        self.health_check_count += 1
        self.last_health_check_payload = {
            "sandbox_id": sandbox_id,
            "timeout": timeout,
        }
        if self.health_check_returns is None:
            raise _not_configured("health_check")
        return self.health_check_returns

    @contextlib.contextmanager
    def prompt_slot(
        self,
        sandbox_id: UUID,
        build_session_id: UUID,
    ) -> Generator[bool, None, None]:
        self.prompt_slot_count += 1
        self.last_prompt_slot_payload = {
            "sandbox_id": sandbox_id,
            "build_session_id": build_session_id,
        }
        yield self.prompt_slot_returns

    def ensure_opencode_session(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        opencode_session_id: str | None = None,
    ) -> str | None:
        # Override the real _ServeMixin preflight (which POSTs /session over
        # HTTP to a pod) so send_message tests run fully in-memory.
        self.ensure_opencode_session_count += 1
        self.last_ensure_opencode_session_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "opencode_session_id": opencode_session_id,
        }
        return self.ensure_opencode_session_returns

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
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Generator[SandboxEvent, None, None]:
        self.send_message_count += 1
        self.last_send_message_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "message": message,
            "opencode_session_id": opencode_session_id,
            "agent_provider": agent_provider,
            "agent_model": agent_model,
            "on_opencode_session_resolved": on_opencode_session_resolved,
            "should_interrupt": should_interrupt,
        }
        if self._send_message_events is None:
            raise _not_configured("send_message")
        # Iterate over the snapshot — re-driveable across calls.
        yield from self._send_message_events

    def subscribe_to_opencode_session(
        self,
        sandbox_id: UUID,
        opencode_session_id: str,
        *,
        directory: str,
        keepalive_seconds: float = 15.0,
    ) -> Generator[SandboxEvent, None, None]:
        self.subscribe_to_opencode_session_count += 1
        self.last_subscribe_to_opencode_session_payload = {
            "sandbox_id": sandbox_id,
            "opencode_session_id": opencode_session_id,
            "directory": directory,
            "keepalive_seconds": keepalive_seconds,
        }
        if self._subscribe_to_opencode_session_events is None:
            raise _not_configured("subscribe_to_opencode_session")
        yield from self._subscribe_to_opencode_session_events

    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        self.list_directory_count += 1
        self.last_list_directory_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "path": path,
        }
        if self.list_directory_returns is None:
            raise _not_configured("list_directory")
        return self.list_directory_returns

    def read_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bytes:
        self.read_file_count += 1
        self.last_read_file_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "path": path,
        }
        if self.read_file_returns is None:
            raise _not_configured("read_file")
        return self.read_file_returns

    def upload_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        self.upload_file_count += 1
        self.last_upload_file_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "filename": filename,
            "content": content,
        }
        if self.upload_file_returns is None:
            raise _not_configured("upload_file")
        return self.upload_file_returns

    def delete_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        path: str,
    ) -> bool:
        self.delete_file_count += 1
        self.last_delete_file_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "path": path,
        }
        if self.delete_file_returns is None:
            raise _not_configured("delete_file")
        return self.delete_file_returns

    def delete_opencode_session(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        opencode_session_id: str,
    ) -> bool:
        self.delete_opencode_session_count += 1
        self.last_delete_opencode_session_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "opencode_session_id": opencode_session_id,
        }
        if isinstance(self.delete_opencode_session_returns, Exception):
            raise self.delete_opencode_session_returns
        return self.delete_opencode_session_returns

    def write_sandbox_file(
        self,
        sandbox_id: UUID,
        path: str,
        content: str,
    ) -> None:
        self.write_sandbox_file_count += 1
        self.last_write_sandbox_file_payload = {
            "sandbox_id": sandbox_id,
            "path": path,
            "content": content,
        }
        if not self.write_sandbox_file_silent:
            raise _not_configured("write_sandbox_file")

    def get_upload_stats(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> tuple[int, int]:
        self.get_upload_stats_count += 1
        self.last_get_upload_stats_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
        }
        if self.get_upload_stats_returns is None:
            raise _not_configured("get_upload_stats")
        return self.get_upload_stats_returns

    def _load_serve_connection_info(
        self, sandbox_id: UUID
    ) -> ServeConnectionInfo | None:
        # Stub doesn't drive a real opencode-serve — return a deterministic
        # URL + no password so any code path that touches the cache gets a
        # reasonable value.
        return ServeConnectionInfo(
            base_url=f"http://stub-{str(sandbox_id)[:8]}:4096",
            password=None,
        )

    def write_files_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
    ) -> None:
        self.write_files_to_sandbox_count += 1
        self.last_write_files_to_sandbox_payload = {
            "sandbox_id": sandbox_id,
            "mount_path": mount_path,
            "files": files,
        }
        if self.write_files_to_sandbox_raises_for is not None:
            exc = self.write_files_to_sandbox_raises_for.get(sandbox_id)
            if exc is not None:
                raise exc
            # A non-empty fault map implies the method is configured; sandboxes
            # not present in the map succeed silently.
            return
        if not self.write_files_to_sandbox_silent:
            raise _not_configured("write_files_to_sandbox")

    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        self.get_webapp_url_count += 1
        self.last_get_webapp_url_payload = {
            "sandbox_id": sandbox_id,
            "port": port,
        }
        if self.get_webapp_url_returns is None:
            raise _not_configured("get_webapp_url")
        return self.get_webapp_url_returns

    def generate_pptx_preview(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        pptx_path: str,
        cache_dir: str,
    ) -> tuple[list[str], bool]:
        self.generate_pptx_preview_count += 1
        self.last_generate_pptx_preview_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "pptx_path": pptx_path,
            "cache_dir": cache_dir,
        }
        if self.generate_pptx_preview_returns is None:
            raise _not_configured("generate_pptx_preview")
        return self.generate_pptx_preview_returns
