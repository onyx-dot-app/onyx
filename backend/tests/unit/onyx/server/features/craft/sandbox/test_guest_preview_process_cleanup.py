"""Preview cleanup must release ports held by children after their leader exits."""

import errno
import json
import os
import select
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from onyx.server.features.build.sandbox.image.guest.operations import (
    PIDFD_SIGNAL_PROCESS_GROUP,
    stop_session_preview,
)

CHILD = """
import json
import os
import signal
import socket
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    print(json.dumps({"pid": os.getpid(), "port": listener.getsockname()[1]}), flush=True)
    while True:
        time.sleep(60)
"""

LEADER = """
import subprocess
import sys
import time

subprocess.Popen([sys.executable, "-B", "-c", sys.argv[1]])
while True:
    time.sleep(60)
"""


@pytest.mark.parametrize("matches_workspace", [True, False])
def test_cleanup_stops_owned_preview_children_after_leader_exits(
    tmp_path: Path, matches_workspace: bool
) -> None:
    if sys.platform != "linux":
        pytest.skip("guest process cleanup uses Linux pidfds and procfs")

    try:
        probe_fd = os.pidfd_open(os.getpid())
    except OSError as error:
        if error.errno == errno.ENOSYS:
            pytest.skip("guest process cleanup requires Linux pidfds")
        raise
    try:
        signal.pidfd_send_signal(probe_fd, 0, None, PIDFD_SIGNAL_PROCESS_GROUP)
    except ProcessLookupError:
        # The test process need not lead a process group.
        pass
    except OSError as error:
        if error.errno in (errno.EINVAL, errno.ENOSYS):
            pytest.skip("guest process cleanup requires pidfd process-group signals")
        raise
    finally:
        os.close(probe_fd)

    root = tmp_path / "session"
    web = root / "outputs" / "web"
    web.mkdir(parents=True)
    leader = subprocess.Popen(
        [sys.executable, "-B", "-c", LEADER, CHILD],
        cwd=web if matches_workspace else tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    child_fd: int | None = None
    try:
        assert leader.stdout is not None
        assert select.select([leader.stdout], [], [], 10)[0], "child did not start"
        ready = json.loads(leader.stdout.readline())
        child_pid = int(ready["pid"])
        port = int(ready["port"])
        child_fd = os.pidfd_open(child_pid)
        assert os.getpgid(leader.pid) == leader.pid
        assert os.getpgid(child_pid) == leader.pid
        assert select.select([child_fd], [], [], 0)[0] == []
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
        (root / "nextjs.pid").write_text(f"{leader.pid}\n")

        stop_session_preview(root)

        if matches_workspace:
            leader.wait(timeout=1)
            assert select.select([child_fd], [], [], 1)[0] == [child_fd]
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", port))
                probe.listen(1)
        else:
            assert leader.poll() is None
            assert select.select([child_fd], [], [], 0)[0] == []
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                pass
    finally:
        if child_fd is not None:
            try:
                signal.pidfd_send_signal(child_fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(child_fd)
        leader.kill()
        leader.wait(timeout=5)
        if leader.stdout is not None:
            leader.stdout.close()
        if leader.stderr is not None:
            leader.stderr.close()
