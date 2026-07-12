from __future__ import annotations

import pytest

from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.session.manager import _is_hidden_workspace_entry


@pytest.mark.parametrize(
    "name",
    [
        "nextjs.log",
        "nextjs.pid",
        ".next",
        "node_modules",
        ".env",
    ],
)
def test_runtime_artifacts_are_hidden(name: str) -> None:
    entry = FilesystemEntry(name=name, path=name, is_directory=False)
    assert _is_hidden_workspace_entry(entry) is True


@pytest.mark.parametrize("name", ["page.tsx", "outputs", "README.md"])
def test_user_files_are_visible(name: str) -> None:
    entry = FilesystemEntry(name=name, path=name, is_directory=False)
    assert _is_hidden_workspace_entry(entry) is False
