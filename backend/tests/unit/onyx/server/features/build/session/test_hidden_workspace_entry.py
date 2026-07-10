from __future__ import annotations

import pytest

from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.session.manager import _is_hidden_workspace_entry


@pytest.mark.parametrize(
    "name",
    [
        "nextjs.log",
        "nextjs.pid",
        "node_modules",
        "opencode.json",
        ".env",
        ".git",
    ],
)
def test_hidden_entries_are_filtered(name: str) -> None:
    entry = FilesystemEntry(name=name, path=name, is_directory=False)
    assert _is_hidden_workspace_entry(entry) is True


@pytest.mark.parametrize(
    "name", ["page.tsx", "README.md", "outputs", "nextjs.log.bak", "mynextjs.pid"]
)
def test_visible_entries_are_kept(name: str) -> None:
    entry = FilesystemEntry(name=name, path=name, is_directory=False)
    assert _is_hidden_workspace_entry(entry) is False
