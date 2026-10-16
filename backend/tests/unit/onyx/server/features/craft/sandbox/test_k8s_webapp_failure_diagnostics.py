"""Bootstrap failure diagnostics retain fixed facts without private output."""

from __future__ import annotations

import io
import shlex
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from onyx.server.features.build.sandbox.models import SandboxExecError
from tests.integration.tests.craft.k8s import k8s_fixtures

_SESSION_ID = UUID("12345678-1234-1234-1234-1234567890ab")
_SESSION_PATH = f"{k8s_fixtures.SESSIONS_ROOT}/{_SESSION_ID}"


@pytest.mark.parametrize(
    "error_label",
    [
        "EADDRINUSE",
        "EACCES",
        "ENOENT",
        "ENOSPC",
        "Cannot find module",
        "Module not found",
        "Could not resolve",
        "JavaScript heap out of memory",
        "Reached heap limit",
        "Failed to compile",
        "Build failed",
        "Turbopack build failed",
        "TurbopackInternalError",
        "An unexpected Turbopack error occurred",
    ],
)
def test_bootstrap_failure_keeps_labels_and_scalars_without_secrets(
    error_label: str,
) -> None:
    error = SandboxExecError(
        "exception-message-secret",
        returncode=1,
        stderr=(
            "server did not become ready\n"
            f"{error_label}: private-module-path-secret\n"
            "Authorization: Bearer bearer-token-secret\n"
            "Cookie: session=cookie-secret\n"
            "password=password-secret\n"
        ),
    )
    with patch.object(
        k8s_fixtures,
        "pod_exec",
        side_effect=[
            error,
            "expected_port=3999\nrecorded_pid=123\nprocess_alive=1\n"
            "process_state=S\ntcp_listening=0\nhttp_status_ipv4=503\n"
            "disk_free_bytes=1048576\nmem_total_kib=8192\nmemory_available_kib=4096\n"
            "oom_kill_count=0\nmem_total_kib=memory-secret\noom_kill_count=oom-secret\n"
            "metadata=metadata-secret\nrecorded_pid=pid-secret\n"
            "process_state=state-secret\nexpected_port=123456789012345678901\n",
        ],
    ) as pod_exec:
        with pytest.raises(AssertionError) as raised:
            k8s_fixtures.start_session_webapp(MagicMock(), "owned-pod", _SESSION_ID)

    assert str(raised.value) == (
        "Webapp bootstrap failed with exit code 1; "
        f"sanitized stderr=server did not become ready\n{error_label}; "
        "runtime facts=expected_port=3999, recorded_pid=123, process_alive=1, "
        "process_state=S, tcp_listening=0, http_status_ipv4=503, "
        "disk_free_bytes=1048576, mem_total_kib=8192, memory_available_kib=4096, "
        "oom_kill_count=0"
    )
    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    assert pod_exec.call_count == 2
    assert pod_exec.call_args_list[0].kwargs == {
        "timeout_s": k8s_fixtures.WEBAPP_BOOTSTRAP_TIMEOUT_S
    }
    assert pod_exec.call_args.kwargs == {"timeout_s": 8.0}


@pytest.mark.parametrize(
    "diagnostic_result",
    [
        RuntimeError("diagnostic-message-secret"),
        SandboxExecError(
            "diagnostic-message-secret", stderr="diagnostic-stderr-secret"
        ),
        "Authorization: Bearer unexpected-output-secret",
    ],
)
def test_diagnostic_failure_preserves_bootstrap_failure(
    diagnostic_result: Exception | str,
) -> None:
    with patch.object(
        k8s_fixtures,
        "pod_exec",
        side_effect=[
            SandboxExecError("bootstrap-message-secret", returncode=7),
            diagnostic_result,
        ],
    ):
        with pytest.raises(AssertionError) as raised:
            k8s_fixtures.start_session_webapp(MagicMock(), "owned-pod", _SESSION_ID)

    assert str(raised.value) == (
        "Webapp bootstrap failed with exit code 7; "
        "sanitized stderr=(empty or unrecognized stderr); runtime facts=unavailable"
    )
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def test_successful_bootstrap_does_not_run_failure_probe() -> None:
    output = "web app dev server running on port 3999"
    with (
        patch.object(
            k8s_fixtures, "pod_exec", side_effect=[output, "INSTALLED"]
        ) as pod_exec,
        patch.object(k8s_fixtures.time, "monotonic", side_effect=[100.0, 101.0]),
    ):
        assert (
            k8s_fixtures.start_session_webapp(MagicMock(), "owned-pod", _SESSION_ID)
            == output
        )

    assert pod_exec.call_count == 2
    assert pod_exec.call_args.args[3] == k8s_fixtures.webapp_install_check_command(
        _SESSION_ID
    )


@pytest.mark.parametrize(
    ("port_text", "pid_text", "expected_prefix"),
    [
        (
            "3999\n",
            "123\n",
            "expected_port=3999, recorded_pid=123, process_alive=1, process_cwd_matches=1, "
            "process_state=S, tcp_listening=1, tcp6_listening=0, http_status_ipv4=503, "
            "disk_free_bytes=1048576, disk_free_inodes=100, ",
        ),
        (
            "65536\n",
            "invalid-pid-secret\n",
            "expected_port=0, recorded_pid=0, "
            "disk_free_bytes=1048576, disk_free_inodes=100, ",
        ),
    ],
)
@pytest.mark.parametrize("kernel_facts_available", [True, False])
def test_failure_probe_uses_only_fixed_files_and_scalars(
    port_text: str,
    pid_text: str,
    expected_prefix: str,
    kernel_facts_available: bool,
) -> None:
    files = {
        f"{_SESSION_PATH}/.nextjs-port": port_text,
        f"{_SESSION_PATH}/nextjs.pid": pid_text,
        "/proc/123/stat": "123 (private-command-secret) S 1 123\n",
        "/proc/net/tcp": (
            "sl local_address rem_address st\n0: 00000000:0F9F 00000000:0000 0A\n"
        ),
        "/proc/net/tcp6": "sl local_address rem_address st\n",
        "/proc/meminfo": "MemTotal: 8192 kB\nMemAvailable: 4096 kB\n",
        "/proc/vmstat": "oom_kill 3\nprivate_kernel_value kernel-secret\n",
    }
    if not kernel_facts_available:
        files["/proc/meminfo"] = "MemAvailable: 4096 kB\n"
        del files["/proc/vmstat"]
    connection = MagicMock()
    connection.getresponse.return_value.status = 503

    def open_file(path: Path) -> io.StringIO:
        if str(path) not in files:
            raise FileNotFoundError(path)
        return io.StringIO(files[str(path)])

    def probe(
        _client: object, _pod: str, _namespace: str, command: str, *, timeout_s: float
    ) -> str:
        argv = shlex.split(command)
        assert argv[0:2] == ["python3", "-c"]
        assert argv[3:] == [_SESSION_PATH]
        assert timeout_s == 8.0
        output = io.StringIO()
        with (
            patch("sys.argv", ["-c", _SESSION_PATH]),
            patch.object(Path, "open", open_file),
            patch.object(Path, "exists", lambda path: str(path) == "/proc/123"),
            patch("os.readlink", return_value=f"{_SESSION_PATH}/outputs/web"),
            patch(
                "os.statvfs",
                return_value=MagicMock(f_bavail=256, f_frsize=4096, f_favail=100),
            ),
            patch(
                "http.client.HTTPConnection", return_value=connection
            ) as http_connection,
            redirect_stdout(output),
        ):
            exec(argv[2], {})
        if port_text == "3999\n":
            http_connection.assert_called_once_with("127.0.0.1", 3999, timeout=2)
        else:
            http_connection.assert_not_called()
        return output.getvalue()

    with patch.object(k8s_fixtures, "pod_exec", side_effect=probe):
        facts = k8s_fixtures._session_webapp_failure_facts(
            MagicMock(), "owned-pod", _SESSION_ID
        )

    expected_kernel_facts = (
        "mem_total_kib=8192, memory_available_kib=4096, oom_kill_count=3"
        if kernel_facts_available
        else "memory_available_kib=4096"
    )
    assert facts == expected_prefix + expected_kernel_facts
    if port_text == "3999\n":
        connection.request.assert_called_once_with("GET", "/")
        connection.close.assert_called_once_with()
    else:
        assert connection.mock_calls == []
