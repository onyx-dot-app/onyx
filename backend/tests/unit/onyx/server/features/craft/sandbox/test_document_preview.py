"""Document converter response validation shared by both sandbox backends."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.server.features.build.sandbox.base import (
    SandboxManager,
    document_preview_command,
    parse_document_preview_response,
)
from onyx.server.features.build.sandbox.models import (
    FatalWriteError,
    PushResult,
    RetriableWriteError,
)

_ROOT: str = "/workspace/sessions/session"


@pytest.mark.parametrize("status,cached", [("CACHED", True), ("GENERATED", False)])
def test_page_paths_are_session_relative(status: str, cached: bool) -> None:
    assert parse_document_preview_response(
        f"{status}\n{_ROOT}/outputs/cache/slide-01.jpg\n{_ROOT}/outputs/cache/slide-02.jpg\n",
        _ROOT,
    ) == (["outputs/cache/slide-01.jpg", "outputs/cache/slide-02.jpg"], cached)


@pytest.mark.parametrize(
    "output",
    [
        "",
        "traceback\nconversion failed",
        "GENERATED",
        "ERROR_SOURCE_CHANGED",
        "ERROR_TIMEOUT",
        "ERROR_CONVERSION",
    ],
)
def test_failed_or_incomplete_conversion_is_not_an_empty_success(output: str) -> None:
    with pytest.raises(ValueError):
        parse_document_preview_response(output, _ROOT)


@pytest.mark.parametrize(
    "path",
    [
        "/workspace/sessions/other/outputs/slide-1.jpg",
        f"{_ROOT}/../other/slide-1.jpg",
        "outputs/slide-1.jpg",
        f"{_ROOT}/outputs/document.pdf",
        f"{_ROOT}/outputs/slide-invalid.jpg",
    ],
)
def test_invalid_page_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValueError):
        parse_document_preview_response(f"GENERATED\n{path}", _ROOT)


def test_packaged_converter_runs_without_managed_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.server.features.build.sandbox import base

    bundle = tmp_path / "converter"
    for name, content in base._DOCUMENT_PREVIEW_FILES.items():
        destination = bundle / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    source = tmp_path / "report.pptx"
    source.write_bytes(b"presentation")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # Stub external binaries; run the real package and office helper normally.
    for name, script in {
        "soffice": '#!/bin/sh\nwhile [ "$1" != "--outdir" ]; do shift; done\nprintf PDF > "$2/report.pdf"\n',
        "pdftoppm": '#!/bin/sh\nfor argument do prefix="$argument"; done\nprintf JPEG > "$prefix-1.jpg"\n',
    }.items():
        executable = binaries / name
        executable.write_text(script)
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binaries}:{os.environ['PATH']}")
    command = document_preview_command(
        str(source),
        str(tmp_path / "cache"),
        str(tmp_path),
        script_path=str(bundle / "preview.py"),
        first_page_only=True,
    )
    result = subprocess.run(
        [sys.executable, *command[1:]],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
    )
    assert result.stdout.splitlines()[0] == "GENERATED"
    assert (tmp_path / "cache/slide-1.jpg").read_bytes() == b"JPEG"
    assert not (tmp_path / "skills").exists()


def test_incomplete_bundle_is_deployed_and_complete_bundle_is_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.server.features.build.sandbox import base

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "preview.py").write_text("old partial upload")
    monkeypatch.setattr(base, "_DOCUMENT_PREVIEW_MOUNT", str(bundle))

    def write_files(**_kwargs: object) -> PushResult:
        for name, content in base._DOCUMENT_PREVIEW_FILES.items():
            destination = bundle / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        return PushResult(targets=1, succeeded=1, failures=[])

    writer = MagicMock(side_effect=write_files)
    manager = SimpleNamespace(push_to_sandbox=writer)

    def run_command(command: list[str]) -> str:
        return subprocess.run(
            command, capture_output=True, text=True, check=True
        ).stdout

    sandbox_id = uuid4()
    SandboxManager._ensure_document_preview_bundle(
        cast(SandboxManager, manager), sandbox_id, run_command
    )
    SandboxManager._ensure_document_preview_bundle(
        cast(SandboxManager, manager), sandbox_id, run_command
    )
    assert writer.call_count == 1
    assert writer.call_args.kwargs["mount_path"] == str(bundle)
    assert (bundle / "office/soffice.py").read_bytes() == base._DOCUMENT_PREVIEW_FILES[
        "office/soffice.py"
    ]


def test_failed_bundle_deployment_is_not_marked_ready() -> None:
    manager = SimpleNamespace(
        push_to_sandbox=MagicMock(
            return_value=PushResult(targets=1, succeeded=1, failures=[])
        )
    )
    with pytest.raises(RuntimeError, match="deployment is incomplete"):
        SandboxManager._ensure_document_preview_bundle(
            cast(SandboxManager, manager), uuid4(), lambda _command: "MISSING"
        )


# Atomic bundle publication shared by skills and document previews.
def test_docker_bundle_swap_keeps_previous_readers_and_complete_concurrent_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.server.features.build.sandbox.docker import (
        docker_sandbox_manager as docker,
    )

    manager = docker.DockerSandboxManager.__new__(docker.DockerSandboxManager)
    monkeypatch.setattr(manager, "_require_container", MagicMock())
    mount = tmp_path / "converter"

    def execute_archive(_container: object, command: list[str], archive: bytes) -> None:
        script = command[2]
        # BSD mv uses -h for the same no-follow behavior as GNU mv -T.
        if sys.platform == "darwin":
            script = script.replace("mv -Tf", "mv -fh")
        # Keep grace-period directories in this test; tmp_path removes them.
        script = script.replace(
            '(sleep 60; rm -rf "$old_target") </dev/null >/dev/null 2>&1 &', ":"
        )
        subprocess.run(
            ["sh", "-c", script], input=archive, check=True, capture_output=True
        )

    monkeypatch.setattr(
        docker, "_stream_stdin_to_container_as_sandbox_user", execute_archive
    )
    sandbox_id = uuid4()

    def push(value: bytes) -> None:
        manager.write_files_to_sandbox(
            sandbox_id=sandbox_id,
            mount_path=str(mount),
            files={"preview.py": value, "office/soffice.py": value},
        )

    push(b"initial")
    previous = mount.resolve()
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(push, [b"second", b"third", b"fourth", b"fifth"]))
    assert mount.is_symlink()
    assert (previous / "preview.py").read_bytes() == b"initial"
    current = mount.resolve()
    assert (current / "preview.py").read_bytes() == (
        current / "office/soffice.py"
    ).read_bytes()
    assert not list(tmp_path.glob("*.link"))


def test_docker_failed_upload_does_not_replace_published_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.server.features.build.sandbox.docker import (
        docker_sandbox_manager as docker,
    )

    manager = docker.DockerSandboxManager.__new__(docker.DockerSandboxManager)
    monkeypatch.setattr(manager, "_require_container", MagicMock())
    mount = tmp_path / "converter"
    prior = tmp_path / "prior"
    prior.mkdir()
    (prior / "preview.py").write_bytes(b"published")
    mount.symlink_to(prior, target_is_directory=True)

    def execute_bad_archive(
        _container: object, command: list[str], _archive: bytes
    ) -> None:
        result = subprocess.run(
            command, input=b"not a tar archive", capture_output=True
        )
        if result.returncode:
            raise docker.ExecError("Invalid archive")

    monkeypatch.setattr(
        docker, "_stream_stdin_to_container_as_sandbox_user", execute_bad_archive
    )
    with pytest.raises(FatalWriteError, match="write_files_to_sandbox failed"):
        manager.write_files_to_sandbox(
            sandbox_id=uuid4(),
            mount_path=str(mount),
            files={"preview.py": b"replacement"},
        )
    assert mount.resolve() == prior
    assert (mount / "preview.py").read_bytes() == b"published"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["converter", "prior"]


# Existing push retry contract
def test_document_bundle_uses_existing_push_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.server.features.build.sandbox import base
    from onyx.server.features.build.sandbox.docker import (
        docker_sandbox_manager as docker,
    )

    manager = docker.DockerSandboxManager.__new__(docker.DockerSandboxManager)
    probes = iter(["MISSING", "READY"])
    writer = MagicMock(
        side_effect=[RetriableWriteError("temporarily unavailable"), None]
    )
    monkeypatch.setattr(manager, "write_files_to_sandbox", writer)
    monkeypatch.setattr(base.time, "sleep", lambda _delay: None)
    manager._ensure_document_preview_bundle(uuid4(), lambda _command: next(probes))
    assert writer.call_count == 2


def test_failed_bundle_push_stops_before_verification() -> None:
    manager = SimpleNamespace(
        push_to_sandbox=MagicMock(
            return_value=PushResult(targets=1, succeeded=0, failures=[])
        )
    )
    runner = MagicMock(return_value="MISSING")
    with pytest.raises(RuntimeError, match="deployment failed"):
        SandboxManager._ensure_document_preview_bundle(
            cast(SandboxManager, manager), uuid4(), runner
        )
    assert runner.call_count == 1


@pytest.mark.parametrize("transient", [True, False])
def test_docker_bundle_writer_classifies_exec_failure(
    monkeypatch: pytest.MonkeyPatch, transient: bool
) -> None:
    from docker.errors import APIError
    from requests import Response

    from onyx.server.features.build.sandbox.docker import (
        docker_sandbox_manager as docker,
    )

    manager = docker.DockerSandboxManager.__new__(docker.DockerSandboxManager)
    monkeypatch.setattr(manager, "_require_container", MagicMock())
    response = Response()
    response.status_code = 503 if transient else 403

    def fail_write(*_args: object) -> None:
        try:
            raise APIError("Engine error", response=response)
        except APIError as error:
            raise docker.ExecError("exec failed") from error

    monkeypatch.setattr(
        docker, "_stream_stdin_to_container_as_sandbox_user", fail_write
    )
    with pytest.raises(RetriableWriteError if transient else FatalWriteError):
        manager.write_files_to_sandbox(
            sandbox_id=uuid4(),
            mount_path="/workspace/managed/test",
            files={"file": b"content"},
        )


@pytest.mark.parametrize(
    "failure", [OSError("socket closed"), TimeoutError("socket timeout")]
)
def test_docker_bundle_writer_marks_socket_failure_retriable(
    monkeypatch: pytest.MonkeyPatch, failure: OSError
) -> None:
    from onyx.server.features.build.sandbox.docker import (
        docker_sandbox_manager as docker,
    )

    manager = docker.DockerSandboxManager.__new__(docker.DockerSandboxManager)
    monkeypatch.setattr(manager, "_require_container", MagicMock())
    monkeypatch.setattr(
        docker,
        "_stream_stdin_to_container_as_sandbox_user",
        MagicMock(side_effect=failure),
    )
    with pytest.raises(RetriableWriteError):
        manager.write_files_to_sandbox(
            sandbox_id=uuid4(),
            mount_path="/workspace/managed/test",
            files={"file": b"content"},
        )
