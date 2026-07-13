from __future__ import annotations

import pytest

from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.session.manager import _is_hidden_workspace_entry


@pytest.mark.parametrize("name", ["nextjs.log", "nextjs.pid"])
def test_dev_server_runtime_files_are_hidden(name: str) -> None:
    entry = FilesystemEntry(name=name, path=name, is_directory=False)
    assert _is_hidden_workspace_entry(entry) is True


def test_regular_files_are_not_hidden() -> None:
    entry = FilesystemEntry(name="page.tsx", path="page.tsx", is_directory=False)
    assert _is_hidden_workspace_entry(entry) is False
