from __future__ import annotations

import pytest

from onyx.server.features.build.sandbox.image.sandbox_daemon.models import (
    is_hidden_workspace_name,
)


@pytest.mark.parametrize(
    "name", ["nextjs.log", "nextjs.pid", "node_modules", "__pycache__", ".preview"]
)
def test_dev_server_runtime_files_are_hidden(name: str) -> None:
    assert is_hidden_workspace_name(name) is True


@pytest.mark.parametrize("name", ["page.tsx", "alpha.txt", "next.config.ts"])
def test_regular_files_are_visible(name: str) -> None:
    assert is_hidden_workspace_name(name) is False
