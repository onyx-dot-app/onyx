"""Guest dispatch must reach bootstrap and setpriv before request imports."""

import json
import os
import signal
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from onyx.server.features.build.sandbox.image.guest import PROTOCOL_VERSION
from onyx.server.features.build.sandbox.image.guest import __main__ as guest_command
from onyx.server.features.build.sandbox.image.guest.input import FramedInput

BACKEND = Path(__file__).resolve().parents[7]
GUEST = "onyx.server.features.build.sandbox.image.guest"
BOOTSTRAP_OPERATIONS = (
    "status",
    "serve",
    "serve-user",
    "restore-history",
    "release-history",
)


def run_bootstrap(operation: str, metadata: str) -> subprocess.CompletedProcess[str]:
    script = f"""
import importlib.abc
import json
import runpy
import sys
sys.path.insert(0, {str(BACKEND)!r})
guest = {GUEST!r}
class BlockHeavyImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('pydantic', guest + '.models', guest + '.operations',
                                guest + '.extract', guest + '.filesystem',
                                guest + '.opencode_history', guest + '.snapshot')):
            raise ImportError('bootstrap loaded ' + fullname)
sys.meta_path.insert(0, BlockHeavyImports())
from {GUEST} import security, supervisor
security.require_root = lambda: None
security.drop_to_user = lambda operation, metadata: None
supervisor.serve = lambda: None
supervisor.serve_user = lambda: None
supervisor.release_history = lambda **kwargs: None
sys.argv = ['onyx_guest', {operation!r}, {metadata!r}]
runpy.run_module(guest + '.__main__', run_name='__main__')
"""
    return subprocess.run(
        [sys.executable, "-I", "-c", script],
        input="\x00" * 4,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


@pytest.mark.parametrize("operation", BOOTSTRAP_OPERATIONS)
def test_bootstrap_skips_request_and_archive_imports(operation: str) -> None:
    result = run_bootstrap(operation, "{}")

    assert result.returncode == 0, result.stderr
    if operation == "status":
        assert json.loads(result.stdout) == {
            "protocol": PROTOCOL_VERSION,
            "ready": False,
            "history_restored": False,
        }


@pytest.mark.parametrize("operation", BOOTSTRAP_OPERATIONS)
@pytest.mark.parametrize(
    "metadata", ["null", "[]", "0", "true", '"{}"', '{"extra":1}', "{}{}"]
)
def test_bootstrap_rejects_nonempty_or_nonobject_metadata(
    operation: str, metadata: str
) -> None:
    result = run_bootstrap(operation, metadata)

    assert result.returncode == 1
    assert result.stderr.startswith(("ValueError:", "JSONDecodeError:")), result.stderr
    assert "bootstrap loaded" not in result.stderr


def test_user_dispatch_reaches_privilege_drop_before_request_imports() -> None:
    script = f"""
import importlib.abc
import runpy
import sys
sys.path.insert(0, {str(BACKEND)!r})
guest = {GUEST!r}
class BlockRequestImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('pydantic', guest + '.models', guest + '.operations',
                                guest + '.extract')):
            raise ImportError('root loaded ' + fullname)
sys.meta_path.insert(0, BlockRequestImports())
from {GUEST} import security
def drop_to_user(operation, metadata):
    raise RuntimeError('reached privilege drop')
security.drop_to_user = drop_to_user
sys.argv = ['onyx_guest', 'run', '{{"argv":["/bin/true"]}}']
runpy.run_module(guest + '.__main__', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        input="\x00" * 4,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert result.stderr.strip() == "RuntimeError: reached privilege drop"


def test_run_imports_use_the_original_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["onyx_guest", "run", '{"argv":["/bin/true"],"timeout_seconds":0.1}'],
    )
    monkeypatch.setattr(guest_command, "drop_to_user", lambda *_args: None)
    monkeypatch.setattr(
        guest_command, "time", Mock(monotonic=Mock(side_effect=[100.0, 112.0]))
    )
    watchdog = Mock()
    monkeypatch.setattr(guest_command.signal, "signal", Mock())
    monkeypatch.setattr(guest_command.signal, "alarm", watchdog)
    launch = Mock(side_effect=AssertionError("expired operation launched a command"))
    monkeypatch.setattr(subprocess, "Popen", launch)

    with pytest.raises(TimeoutError, match="guest operation timed out"):
        guest_command.main(FramedInput(BytesIO(b"\x00" * 4)))

    watchdog.assert_called_once_with(3611)
    launch.assert_not_called()


@pytest.mark.parametrize("run_error", [None, BrokenPipeError])
def test_run_preserves_budget_and_cancels_watchdog(
    monkeypatch: pytest.MonkeyPatch, run_error: type[Exception] | None
) -> None:
    from onyx.server.features.build.sandbox.image.guest import operations

    monkeypatch.setattr(
        sys,
        "argv",
        ["onyx_guest", "run", '{"argv":["/bin/true"],"timeout_seconds":20}'],
    )
    monkeypatch.setattr(guest_command, "drop_to_user", lambda *_args: None)
    monkeypatch.setattr(
        guest_command, "time", Mock(monotonic=Mock(side_effect=[100.0, 112.0]))
    )
    timer = Mock()
    monkeypatch.setattr(guest_command.signal, "signal", Mock())
    monkeypatch.setattr(guest_command.signal, "alarm", Mock())
    monkeypatch.setattr(guest_command.signal, "setitimer", timer)
    run = Mock(return_value=0, side_effect=run_error)
    monkeypatch.setattr(operations, "run", run)
    spool = Mock(side_effect=AssertionError("payload-free run spooled input"))
    monkeypatch.setattr(operations, "spool_stdin", spool)

    with pytest.raises(run_error or SystemExit):
        guest_command.main(FramedInput(BytesIO(b"\x00" * 4)))

    assert timer.call_args_list == [
        call(guest_command.signal.ITIMER_REAL, 19.0),
        call(guest_command.signal.ITIMER_REAL, 0),
    ]
    run.assert_called_once()
    assert run.call_args.args[0].timeout_seconds == 20
    assert run.call_args.kwargs["deadline"] == 120.0
    spool.assert_not_called()


@pytest.mark.parametrize("operation", ["serve", "serve-user"])
@pytest.mark.parametrize("startup_error", [None, RuntimeError])
def test_service_startup_does_not_read_or_drain_rpc_input(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    startup_error: type[Exception] | None,
) -> None:
    monkeypatch.setattr(sys, "argv", ["onyx_guest", operation, "{}"])
    monkeypatch.setattr(guest_command, "drop_to_user", lambda *_args: None)
    monkeypatch.setattr(guest_command, "require_root", lambda: None)
    monkeypatch.setattr(guest_command.signal, "signal", Mock())
    startup = Mock(side_effect=startup_error)
    monkeypatch.setattr(guest_command, operation.replace("-", "_"), startup)
    source = BytesIO(b"startup must leave this input unread")

    if startup_error is None:
        guest_command.main(FramedInput(source))
    else:
        with pytest.raises(startup_error):
            guest_command.main(FramedInput(source))

    startup.assert_called_once_with()
    assert source.tell() == 0


def test_expired_run_budget_does_not_launch_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from onyx.server.features.build.sandbox.image.guest import operations
    from onyx.server.features.build.sandbox.image.guest.models import RunRequest

    monkeypatch.setattr(operations, "time", Mock(monotonic=Mock(return_value=112.0)))
    launch = Mock(side_effect=AssertionError("expired operation launched a command"))
    monkeypatch.setattr(operations.subprocess, "Popen", launch)

    code = operations.run(RunRequest(argv=["/bin/true"]), BytesIO(), deadline=111.0)

    assert code == 124
    assert capsys.readouterr().err == "\ncommand timed out\n"
    launch.assert_not_called()


def test_delayed_stdin_preparation_preserves_timeout_result(tmp_path: Path) -> None:
    pid_file = tmp_path / "command-pids"
    command = f"""
import os
import subprocess
import sys
import time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path({str(pid_file)!r}).write_text(f'{{os.getpid()}} {{child.pid}}')
print('captured command stderr', file=sys.stderr, flush=True)
time.sleep(60)
"""
    metadata = json.dumps(
        {
            "argv": [sys.executable, "-I", "-c", command],
            "cwd": str(tmp_path),
            "timeout_seconds": 12,
            "has_stdin": True,
        }
    )
    script = f"""
import runpy
import sys
import time
sys.path.insert(0, {str(BACKEND)!r})
from {GUEST} import operations, security
security.drop_to_user = lambda *_args: None
spool_stdin = operations.spool_stdin
def delayed_spool(*args, **kwargs):
    time.sleep(11.2)
    spool_stdin(*args, **kwargs)
operations.spool_stdin = delayed_spool
sys.argv = ['onyx_guest', 'run', {metadata!r}]
runpy.run_module({GUEST!r} + '.__main__', run_name='__main__')
"""
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", script],
            input="\x00" * 4,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        assert result.returncode == 124, result.stderr
        assert "captured command stderr" in result.stderr
        assert "command timed out" in result.stderr
        pids = [int(value) for value in pid_file.read_text().split()]
        deadline = time.monotonic() + 2
        alive = pids
        while time.monotonic() < deadline:
            alive = []
            for pid in pids:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                alive.append(pid)
            if not alive:
                break
            time.sleep(0.05)
        assert not alive, f"command descendants remain: {alive}"
    finally:
        if pid_file.exists():
            leader = int(pid_file.read_text().split()[0])
            try:
                os.killpg(leader, signal.SIGKILL)
            except ProcessLookupError:
                pass
