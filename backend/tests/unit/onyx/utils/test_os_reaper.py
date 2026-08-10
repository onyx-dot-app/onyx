"""Validate subreaper adoption + zombie draining (Linux-only).

The scenario runs in an isolated subprocess so the subreaper flag and the
waitpid(-1) drain never touch the pytest process: a child orphans a grandchild,
which must re-parent to the harness (not PID 1) and be drained."""

import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).parents[4]

_HARNESS = """
import os
import sys
import time

from onyx.utils.os_reaper import become_child_subreaper, reap_exited_children

assert become_child_subreaper(), "prctl(PR_SET_CHILD_SUBREAPER) failed"

child_pid = os.fork()
if child_pid == 0:
    # child: orphan a grandchild while it is still running, then exit
    grandchild_pid = os.fork()
    if grandchild_pid == 0:
        time.sleep(0.2)  # outlive the parent so re-parenting happens while alive
        os._exit(0)
    os._exit(0)

os.waitpid(child_pid, 0)  # reap the direct child; only the orphan remains

# the orphaned grandchild re-parents to us (the subreaper) and zombifies on
# exit; without the subreaper flag it would re-parent to PID 1 and this loop
# could never observe it
deadline = time.monotonic() + 10
reaped = 0
while reaped == 0 and time.monotonic() < deadline:
    reaped = reap_exited_children()
    time.sleep(0.05)

assert reaped == 1, f"expected to reap exactly the orphaned grandchild, got {reaped}"
assert reap_exited_children() == 0, "no children should remain"
print("ok")
"""


@pytest.mark.skipif(
    sys.platform != "linux", reason="prctl/waitpid semantics are Linux-only"
)
def test_subreaper_adopts_and_drains_orphaned_grandchild() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _HARNESS],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PYTHONPATH": str(_BACKEND_DIR)},
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_reap_exited_children_noop_without_children() -> None:
    """The drain must be safe to call from a process with no children at all."""
    harness = (
        "from onyx.utils.os_reaper import reap_exited_children\n"
        "assert reap_exited_children() == 0\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", harness],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PYTHONPATH": str(_BACKEND_DIR)},
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
