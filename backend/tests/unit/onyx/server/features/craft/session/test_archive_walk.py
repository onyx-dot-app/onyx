from __future__ import annotations

from uuid import uuid4

from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.session.manager import SessionManager
from tests.common.craft.stubs import StubSandboxManager


def _manager(sandbox_manager: StubSandboxManager) -> SessionManager:
    manager = SessionManager.__new__(SessionManager)
    manager._sandbox_manager = sandbox_manager
    return manager


def test_archive_walk_skips_hidden_entries() -> None:
    sandbox_manager = StubSandboxManager()
    sandbox_manager.list_directory_returns_by_path = {
        "outputs/web": [
            FilesystemEntry(name="app", path="outputs/web/app", is_directory=True),
            FilesystemEntry(name=".next", path="outputs/web/.next", is_directory=True),
            FilesystemEntry(
                name="node_modules",
                path="outputs/web/node_modules",
                is_directory=True,
            ),
        ],
        "outputs/web/app": [
            FilesystemEntry(
                name="page.tsx",
                path="outputs/web/app/page.tsx",
                is_directory=False,
            ),
            FilesystemEntry(
                name=".env",
                path="outputs/web/app/.env",
                is_directory=False,
            ),
            FilesystemEntry(
                name="node_modules",
                path="outputs/web/app/node_modules",
                is_directory=True,
            ),
        ],
        "outputs/web/.next": [
            FilesystemEntry(
                name="server.js",
                path="outputs/web/.next/server.js",
                is_directory=False,
            ),
        ],
        "outputs/web/node_modules": [
            FilesystemEntry(
                name="next.js",
                path="outputs/web/node_modules/next.js",
                is_directory=False,
            ),
        ],
        "outputs/web/app/node_modules": [
            FilesystemEntry(
                name="react.js",
                path="outputs/web/app/node_modules/react.js",
                is_directory=False,
            ),
        ],
    }

    files = _manager(sandbox_manager)._walk_sandbox_dir(
        uuid4(),
        uuid4(),
        "outputs/web",
        arcname_for=lambda path: path.removeprefix("outputs/web/"),
    )

    assert files == [("outputs/web/app/page.tsx", "app/page.tsx")]
    assert [payload["path"] for payload in sandbox_manager.list_directory_payloads] == [
        "outputs/web",
        "outputs/web/app",
    ]
