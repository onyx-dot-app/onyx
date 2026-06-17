from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    DockerSandboxManager,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)

_SANDBOX_ID = UUID("9a5c81d5-931e-4348-b034-3ebd13bcba44")
_SESSION_ID = UUID("903a9a86-b7b1-4b49-9269-1fe558b243ee")

_ROOT_LS_WITH_DANGLING_SYMLINK = """total 16
drwxr-sr-x. 4 sandbox sandbox  111 1781733405 .
drwxrwsrwx. 4 root    sandbox   91 1781733401 ..
-rw-r--r--. 1 sandbox sandbox 6944 1781733405 AGENTS.md
drwxr-xr-x. 3 sandbox sandbox   17 1781733401 outputs
lrwxrwxrwx. 1 sandbox sandbox   31 1781733405 user_library -> /workspace/managed/user_library
"""


def test_kubernetes_list_directory_does_not_follow_child_symlinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    manager._namespace = "sandbox-test"  # type: ignore[attr-defined]
    manager._stream_core_api = SimpleNamespace(  # type: ignore[attr-defined]
        connect_get_namespaced_pod_exec=object()
    )

    monkeypatch.setattr(
        KubernetesSandboxManager,
        "_get_pod_name",
        lambda _self, _sandbox_id: "sandbox-9a5c81d5",
    )

    captured_command: list[str] = []

    def fake_k8s_stream(*_args: Any, **kwargs: Any) -> str:
        captured_command.extend(kwargs["command"])
        return _ROOT_LS_WITH_DANGLING_SYMLINK

    monkeypatch.setattr(ksm, "k8s_stream", fake_k8s_stream)

    entries = manager.list_directory(_SANDBOX_ID, _SESSION_ID, ".")

    entry_by_name = {entry.name: entry for entry in entries}
    assert entry_by_name["outputs"].is_directory
    assert entry_by_name["user_library"].is_directory
    assert not entry_by_name["AGENTS.md"].is_directory

    shell_script = " ".join(captured_command)
    assert "ls -la --time-style=+%s" in shell_script
    assert "ls -laL" not in shell_script
    assert '"$target"/' in shell_script


def test_docker_parse_ls_treats_workspace_symlinks_as_directories() -> None:
    manager: DockerSandboxManager = object.__new__(DockerSandboxManager)

    entries = manager._parse_ls_output(_ROOT_LS_WITH_DANGLING_SYMLINK, ".")

    entry_by_name = {entry.name: entry for entry in entries}
    assert entry_by_name["outputs"].is_directory
    assert entry_by_name["user_library"].is_directory
    assert not entry_by_name["AGENTS.md"].is_directory
