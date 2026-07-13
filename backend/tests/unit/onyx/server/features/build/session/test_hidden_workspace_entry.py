from __future__ import annotations

import pytest

from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.session.manager import _is_hidden_workspace_entry


@pytest.mark.parametrize("name", ["nextjs.log", "nextjs.pid"])
def test_nextjs_runtime_files_are_hidden(name: str) -> None:
    entry = FilesystemEntry(name=name, path=name, is_directory=False)
    assert _is_hidden_workspace_entry(entry) is True


@pytest.mark.parametrize("name", ["outputs", "AGENTS.md", "attachments"])
def test_regular_entries_are_not_hidden(name: str) -> None:
    entry = FilesystemEntry(name=name, path=name, is_directory=True)
    assert _is_hidden_workspace_entry(entry) is False
