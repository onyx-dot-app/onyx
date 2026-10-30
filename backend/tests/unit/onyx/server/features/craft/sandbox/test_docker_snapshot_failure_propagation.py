"""Docker snapshot failure-propagation contract.

The Docker backend streams ``tar`` stdout out of the container through
``_GeneratorReader`` into ``FileStore``. A non-zero ``tar`` exit must surface
as an exception (so ``create_snapshot`` raises and the fail-closed idle-cleanup
keeps the sandbox RUNNING) — it must NOT be silently swallowed as a clean EOF,
which would persist a truncated/corrupt snapshot and lose the workspace on the
next restore. This is the Docker analog of the K8s PIPESTATUS fix.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import onyx.server.features.build.sandbox.docker.docker_sandbox_manager as dsm
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import ExecError


def _ok_stream() -> Generator[bytes, None, int]:
    yield b"hello "
    yield b"world"
    return 0  # clean exit, like stream_stdout_from_container on tar exit 0


def _failing_stream() -> Generator[bytes, None, int]:
    # Mirrors stream_stdout_from_container: yields partial stdout, then its
    # final ``return _check_exit(...)`` RAISES because tar exited non-zero.
    yield b"partial tar bytes"
    raise ExecError("command tar exited with 2: No space left on device")


def test_generator_reader_reads_clean_stream_chunked() -> None:
    reader = dsm._GeneratorReader(_ok_stream())
    out = b""
    while True:
        chunk = reader.read(4)  # chunked, like shutil.copyfileobj
        if not chunk:
            break
        out += chunk
    assert out == b"hello world"


def test_generator_reader_propagates_tar_failure_chunked() -> None:
    """The failure must propagate through chunked read() (the path FileStore
    uses) — not be swallowed by the ``except StopIteration`` branch."""
    reader = dsm._GeneratorReader(_failing_stream())
    with pytest.raises(ExecError):
        # Drain in chunks until exhaustion; the failure surfaces at the end.
        while reader.read(4):
            pass


def test_generator_reader_propagates_tar_failure_read_all() -> None:
    reader = dsm._GeneratorReader(_failing_stream())
    with pytest.raises(ExecError):
        reader.read(-1)


@pytest.mark.parametrize(
    "probe", [ExecError("exec failed"), SimpleNamespace(stdout_text="")]
)
def test_snapshot_probe_failure_is_not_an_empty_checkpoint(
    probe: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(dsm.DockerSandboxManager)
    monkeypatch.setattr(manager, "_get_container", lambda _id: MagicMock())
    run = (
        MagicMock(side_effect=probe)
        if isinstance(probe, ExecError)
        else MagicMock(return_value=probe)
    )
    monkeypatch.setattr(dsm, "_run_in_container_as_sandbox_user", run)
    with pytest.raises(RuntimeError, match="snapshot discovery|Snapshot discovery"):
        manager.create_snapshot(uuid4(), uuid4(), "public")


def test_snapshot_requires_a_present_container(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = object.__new__(dsm.DockerSandboxManager)
    monkeypatch.setattr(manager, "_get_container", lambda _id: None)
    with pytest.raises(RuntimeError, match="missing sandbox"):
        manager.create_snapshot(uuid4(), uuid4(), "public")


@pytest.mark.parametrize("volume_exists", [False, True])
def test_storage_check_preserves_detached_volume(
    volume_exists: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox_id = uuid4()
    manager = object.__new__(dsm.DockerSandboxManager)
    manager._docker = MagicMock()
    monkeypatch.setattr(manager, "_get_container", lambda _id: None)
    if volume_exists:
        manager._docker.volumes.get.return_value.attrs = {
            "CreatedAt": "2026-10-21T00:00:00Z",
            "Labels": {
                dsm.LABEL_SANDBOX_ID: str(sandbox_id),
                dsm.LABEL_TENANT_ID: "public",
            },
        }
    else:
        manager._docker.volumes.get.side_effect = dsm.NotFound("missing")
    assert manager.workspace_storage_exists(sandbox_id, "public") == volume_exists


def test_docker_archive_excludes_output_thumbnail_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox_id, session_id = uuid4(), uuid4()
    session_path: Path = tmp_path / str(session_id)
    (session_path / "outputs/.document-thumbnails/report").mkdir(parents=True)
    (session_path / "attachments/.document-thumbnails").mkdir(parents=True)
    (session_path / "outputs/report.pdf").write_bytes(b"source")
    (session_path / "outputs/user/.document-thumbnails").mkdir(parents=True)
    (session_path / "outputs/user/.document-thumbnails/owned.txt").write_bytes(b"keep")
    (session_path / "outputs/.document-thumbnails/report/slide-1.jpg").write_bytes(
        b"generated"
    )
    (session_path / "outputs/.document-thumbnails/report/.conversion.lock").touch()
    (session_path / "attachments/.document-thumbnails/user-file.txt").write_text("keep")
    monkeypatch.setattr(dsm, "SESSIONS_ROOT", str(tmp_path))
    monkeypatch.setattr(
        dsm.DockerSandboxManager, "_get_container", MagicMock(return_value=object())
    )
    monkeypatch.setattr(
        dsm,
        "_run_in_container_as_sandbox_user",
        MagicMock(return_value=SimpleNamespace(stdout_text="OK")),
    )
    archives: list[bytes] = []

    def stream_archive(
        _container: object, command: list[str]
    ) -> Generator[bytes, None, int]:
        result: subprocess.CompletedProcess[bytes] = subprocess.run(
            command, check=True, capture_output=True
        )
        yield result.stdout
        return 0

    def persist(
        *, stream: dsm._GeneratorReader, **_kwargs: object
    ) -> tuple[str, str, int]:
        archive: bytes = stream.read()
        archives.append(archive)
        return "snapshot", "storage", len(archive)

    monkeypatch.setattr(
        dsm, "_stream_stdout_from_container_as_sandbox_user", stream_archive
    )
    manager: dsm.DockerSandboxManager = dsm.DockerSandboxManager.__new__(
        dsm.DockerSandboxManager
    )
    manager._snapshot_manager = MagicMock()
    manager._snapshot_manager.persist_snapshot_from_stream.side_effect = persist
    assert manager.create_snapshot(sandbox_id, session_id, "public") is not None
    with tarfile.open(fileobj=io.BytesIO(archives[0]), mode="r:gz") as archive:
        names: list[str] = archive.getnames()
    assert "outputs/report.pdf" in names
    assert "outputs/user/.document-thumbnails/owned.txt" in names
    assert "attachments/.document-thumbnails/user-file.txt" in names
    assert not any(name.startswith("outputs/.document-thumbnails") for name in names)
