from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.session.manager import SessionManager
from tests.common.craft.stubs import StubSandboxManager


def _manager(sandbox_manager: StubSandboxManager) -> SessionManager:
    manager = SessionManager.__new__(SessionManager)
    manager._sandbox_manager = sandbox_manager
    sandbox = SimpleNamespace(id=uuid4())
    manager._resolve_owned_session_and_sandbox = (  # type: ignore[method-assign]
        lambda *_: (SimpleNamespace(), sandbox)
    )
    return manager


def test_list_directory_hides_nextjs_dev_server_artifacts() -> None:
    sandbox_manager = StubSandboxManager()
    sandbox_manager.list_directory_returns = [
        FilesystemEntry(name="outputs", path="outputs", is_directory=True),
        FilesystemEntry(name="AGENTS.md", path="AGENTS.md", is_directory=False),
        FilesystemEntry(name="nextjs.log", path="nextjs.log", is_directory=False),
        FilesystemEntry(name="nextjs.pid", path="nextjs.pid", is_directory=False),
    ]

    listing = _manager(sandbox_manager).list_directory(uuid4(), uuid4(), "")

    assert listing is not None
    assert [entry.name for entry in listing.entries] == ["outputs", "AGENTS.md"]
