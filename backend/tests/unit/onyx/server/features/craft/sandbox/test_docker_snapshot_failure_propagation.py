"""Docker snapshot failure-propagation contract.

The Docker backend streams ``tar`` stdout out of the container through
``_GeneratorReader`` into ``FileStore``. A non-zero ``tar`` exit must surface
as an exception (so ``create_snapshot`` raises and the fail-closed idle-cleanup
keeps the sandbox RUNNING) — it must NOT be silently swallowed as a clean EOF,
which would persist a truncated/corrupt snapshot and lose the workspace on the
next restore. This is the Docker analog of the K8s PIPESTATUS fix.
"""

from __future__ import annotations

from collections.abc import Generator

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
