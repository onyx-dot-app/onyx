from __future__ import annotations

import pytest

from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.session.manager import _is_hidden_workspace_entry


@pytest.mark.parametrize(
    ("name", "is_directory", "expected_hidden"),
    [
        ("nextjs.log", False, True),
        ("nextjs.pid", False, True),
        (".env", False, True),
        ("node_modules", True, True),
        ("page.tsx", False, False),
        ("outputs", True, False),
    ],
)
def test_is_hidden_workspace_entry(
    name: str, is_directory: bool, expected_hidden: bool
) -> None:
    entry = FilesystemEntry(name=name, path=name, is_directory=is_directory)
    assert _is_hidden_workspace_entry(entry) is expected_hidden
