"""Workspace file-listing filter hides sandbox runtime artifacts."""

from __future__ import annotations

import pytest

from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.session.manager import _is_hidden_workspace_entry


def _entry(name: str) -> FilesystemEntry:
    return FilesystemEntry(name=name, path=f"/{name}", is_directory=False)


@pytest.mark.parametrize("name", ["nextjs.log", "nextjs.pid"])
def test_nextjs_runtime_files_are_hidden(name: str) -> None:
    assert _is_hidden_workspace_entry(_entry(name)) is True


def test_regular_files_are_not_hidden() -> None:
    assert _is_hidden_workspace_entry(_entry("page.tsx")) is False
