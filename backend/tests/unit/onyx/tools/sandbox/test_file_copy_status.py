"""The bounded [files] status line of background file copies."""

import threading
import time
from typing import cast
from uuid import uuid4

import pytest

from onyx.server.features.build.sandbox.harness_base import (
    HarnessSandbox,
    SessionFiles,
)
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.tools.tool_implementations.sandbox import file_copies
from onyx.tools.tool_implementations.sandbox.file_copies import (
    CopyState,
    CopyStatus,
    FileCopyPool,
    TurnFileCopies,
)
from onyx.tools.tool_implementations.sandbox.models import VmChatFile
from tests.unit.fakes import FakeCache


class _SlowSetup:
    """A sandbox whose session setup waits, then raises."""

    def __init__(self) -> None:
        self.setting_up = threading.Event()
        self.fail = threading.Event()

    def session_files(self, ref: HarnessSandboxRef) -> SessionFiles:  # noqa: ARG002
        self.setting_up.set()
        self.fail.wait()
        raise RuntimeError("no sandbox")


@pytest.mark.parametrize("files", [2_000, 10_000])
def test_the_status_line_stays_bounded_for_any_file_count(
    monkeypatch: pytest.MonkeyPatch, files: int
) -> None:
    cache = FakeCache()
    monkeypatch.setattr(file_copies, "get_cache_backend", lambda **_kwargs: cache)
    pool = FileCopyPool()
    monkeypatch.setattr(file_copies, "file_copy_pool", lambda: pool)
    sandbox = _SlowSetup()
    names = [f"attachments/file-{i:05}.csv" for i in range(files)]
    copies = TurnFileCopies(
        HarnessSandboxRef(tenant_id="tenant", sandbox_id=uuid4(), session_id=uuid4()),
        cast(HarnessSandbox, sandbox),
        [VmChatFile(file_id=f"f{i}", path=name) for i, name in enumerate(names)],
    )
    try:
        assert sandbox.setting_up.wait(5)

        # Before the copy takes the files in, every file counts as copying.
        line = copies.status.line()
        assert line == (
            f"[files] Copying: {', '.join(names[:5])}, and {files - 5:,} more."
        )
        assert copies.status.line() is None

        sandbox.fail.set()
        deadline = time.monotonic() + 5
        while (line := copies.status.line()) is None:
            assert time.monotonic() < deadline, "the copy did not end"
            time.sleep(0.01)  # test-flakes: allow polls the status until a deadline
        reason = " (the sandbox did not start)"
        assert line == (
            "[files] Failed: "
            + "; ".join(name + reason for name in names[:5])
            + f"; and {files - 5:,} more; retrying next turn."
        )
        assert len(line) < 1_000
    finally:
        sandbox.fail.set()
        pool.shutdown()


def test_a_change_that_renders_the_same_line_gives_no_line() -> None:
    names = [f"attachments/{i}.csv" for i in range(7)]
    status = CopyStatus(names)
    assert status.line() == (f"[files] Copying: {', '.join(names[:5])}, and 2 more.")
    # A state set again renders the same line.
    status.update([(names[6], CopyState.COPYING, None)])
    assert status.line() is None
    status.update([(names[0], CopyState.FAILED, "the sandbox did not start")])
    assert status.line() is not None
