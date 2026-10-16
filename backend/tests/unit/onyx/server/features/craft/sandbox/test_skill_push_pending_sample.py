"""Pending skill enable diagnostics preserve the request outcome and private data."""

from __future__ import annotations

import io
import os
import shlex
import stat
from concurrent.futures import Future
from contextlib import redirect_stdout
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from onyx.server.features.build.sandbox.models import SandboxExecError
from onyx.server.features.skill.models import SkillResponse
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.k8s import test_skill_push as subject


def test_fast_enable_preserves_context_and_response_without_a_sample() -> None:
    context = ContextVar("skill-sample-test", default="missing")
    token = context.set("request-context")
    skill = MagicMock(spec=SkillResponse)
    user = MagicMock(spec=DATestUser)

    def enable(
        actual_skill: SkillResponse, actual_user: DATestUser, enabled: bool
    ) -> SkillResponse:
        assert (actual_skill, actual_user, enabled) == (skill, user, True)
        assert context.get() == "request-context"
        return skill

    try:
        with (
            patch.object(subject.SkillManager, "set_enabled", side_effect=enable),
            patch.object(subject, "pod_exec") as pod_exec,
        ):
            assert (
                subject._enable_skill_with_pending_push_sample(skill, user, MagicMock())
                is skill
            )
        pod_exec.assert_not_called()
    finally:
        context.reset(token)


@pytest.mark.parametrize(
    "original_error",
    [
        RuntimeError("request-secret"),
        httpx.ReadTimeout("request-secret"),
        TimeoutError("request-secret"),
    ],
)
def test_completed_failure_keeps_the_original_exception_without_a_sample(
    original_error: Exception,
) -> None:
    future: Future[SkillResponse] = Future()
    future.set_exception(original_error)
    with (
        patch.object(subject, "start_thread_future", return_value=future),
        patch.object(subject, "pod_exec") as pod_exec,
        pytest.raises(type(original_error)) as raised,
    ):
        subject._enable_skill_with_pending_push_sample(
            MagicMock(), MagicMock(), MagicMock()
        )
    assert raised.value is original_error
    pod_exec.assert_not_called()


@pytest.mark.parametrize("fails", [False, True])
def test_pending_enable_samples_once_then_preserves_the_original_outcome(
    fails: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    skill = MagicMock(spec=SkillResponse)
    user = MagicMock(spec=DATestUser)
    workspace = subject.WorkspaceProxy(MagicMock(), "owned-user-b-pod")
    original_error = httpx.ReadTimeout("request-secret")
    future = MagicMock(spec=Future)
    future.result.side_effect = [TimeoutError(), original_error if fails else skill]
    future.done.return_value = False
    with (
        patch.object(subject, "start_thread_future", return_value=future) as start,
        patch.object(subject.SkillManager, "set_enabled", return_value=skill) as enable,
        patch.object(
            subject,
            "pod_exec",
            return_value="summary helper_count=1\nhelper pid=123 state=S wait=pipe_read metadata=payload-secret\n",
        ) as pod_exec,
    ):
        if fails:
            with pytest.raises(httpx.ReadTimeout) as raised:
                subject._enable_skill_with_pending_push_sample(skill, user, workspace)
            assert raised.value is original_error
        else:
            assert (
                subject._enable_skill_with_pending_push_sample(skill, user, workspace)
                is skill
            )
        assert start.call_args.args[0]() is skill
        enable.assert_called_once_with(skill, user, True)
    assert start.call_args.kwargs == {"name": "skill-enable-pending-push"}
    assert future.result.call_args_list == [call(timeout=5.0), call()]
    assert pod_exec.call_count == 1
    assert pod_exec.call_args.args[:3] == (
        workspace._k8s_client,
        "owned-user-b-pod",
        subject.SANDBOX_NAMESPACE,
    )
    assert pod_exec.call_args.kwargs == {"root": True, "timeout_s": 5.0}
    assert capsys.readouterr().out == (
        "Managed push pending; facts=summary helper_count=1 | helper pid=123 state=S wait=pipe_read\n"
    )


def test_completion_at_initial_wait_skips_the_sample() -> None:
    skill = MagicMock(spec=SkillResponse)
    future = MagicMock(spec=Future)
    future.result.side_effect = [TimeoutError(), skill]
    future.done.return_value = True
    with (
        patch.object(subject, "start_thread_future", return_value=future),
        patch.object(subject, "pod_exec") as pod_exec,
    ):
        assert (
            subject._enable_skill_with_pending_push_sample(
                MagicMock(), MagicMock(), MagicMock()
            )
            is skill
        )
    assert future.result.call_args_list == [call(timeout=5.0), call()]
    pod_exec.assert_not_called()


@pytest.mark.parametrize(
    ("sample_error", "expected_class"),
    [
        (RuntimeError("sample-message-secret"), "RuntimeError"),
        (
            SandboxExecError("sample-message-secret", stderr="sample-stderr-secret"),
            "SandboxExecError",
        ),
        (
            type("private-class-secret\n", (Exception,), {})("sample-message-secret"),
            "Exception",
        ),
    ],
)
@pytest.mark.parametrize("request_fails", [False, True])
def test_sample_failure_prints_only_class_and_keeps_request_outcome(
    sample_error: Exception,
    expected_class: str,
    request_fails: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_error = httpx.ReadTimeout("request-secret")
    skill = MagicMock(spec=SkillResponse)
    future = MagicMock(spec=Future)
    future.result.side_effect = [
        TimeoutError(),
        original_error if request_fails else skill,
    ]
    future.done.return_value = False
    with (
        patch.object(subject, "start_thread_future", return_value=future),
        patch.object(subject, "pod_exec", side_effect=sample_error) as pod_exec,
    ):
        if request_fails:
            with pytest.raises(httpx.ReadTimeout) as raised:
                subject._enable_skill_with_pending_push_sample(
                    skill, MagicMock(), MagicMock()
                )
            assert raised.value is original_error
        else:
            assert (
                subject._enable_skill_with_pending_push_sample(
                    skill, MagicMock(), MagicMock()
                )
                is skill
            )
    assert pod_exec.call_count == 1
    assert (
        capsys.readouterr().out
        == f"Managed push sample failed; exception={expected_class}\n"
    )


def test_broken_diagnostic_output_keeps_original_request_exception() -> None:
    original_error = httpx.ReadTimeout("request-secret")
    future = MagicMock(spec=Future)
    future.result.side_effect = [TimeoutError(), original_error]
    future.done.return_value = False
    with (
        patch.object(subject, "start_thread_future", return_value=future),
        patch.object(subject, "pod_exec", return_value="summary helper_count=0"),
        patch("builtins.print", side_effect=BrokenPipeError("output-secret")),
        pytest.raises(httpx.ReadTimeout) as raised,
    ):
        subject._enable_skill_with_pending_push_sample(
            MagicMock(), MagicMock(), MagicMock()
        )
    assert raised.value is original_error


def test_host_projects_only_known_scalar_fields_and_categories() -> None:
    output = (
        "summary helper_count=1 total_kib=8192 available_kib=4096 metadata=secret\n"
        "summary helper_count=2\n"
        "helper pid=123 state=S wait=flock_wait utime_ticks=11 stime_ticks=12 fd0=fifo fd1=socket fd2=char rss_kib=64\n"
        "helper pid=0 state=secret\n"
        "helper pid=124 state=secret wait=secret fd0=secret rss_kib=-1 utime_ticks=9223372036854775808 stime_ticks=123456789012345678901 metadata=secret\n"
        "lock owner_pid=123 waiter_pid=124 metadata=secret\n"
        "lock owner_pid=2147483648 waiter_pid=0\n"
        "secret pid=123\n"
        "helper pid=１２３ state=secret\n"
    )
    with patch.object(subject, "pod_exec", return_value=output):
        facts = subject._pending_managed_push_facts(MagicMock())
    assert facts == (
        "summary helper_count=1 total_kib=8192 available_kib=4096 | "
        "helper pid=123 state=S wait=flock_wait utime_ticks=11 stime_ticks=12 fd0=fifo fd1=socket fd2=char rss_kib=64 | "
        "helper pid=124 | lock owner_pid=123 waiter_pid=124"
    )


def test_host_bounds_helper_lock_rows_and_raw_output() -> None:
    output = "\n".join(f"helper pid={pid}" for pid in range(1, 21))
    output += "\n" + "\n".join(f"lock owner_pid={pid}" for pid in range(1, 41))
    output += "\n" + "x" * 4096 + "\nsummary helper_count=1"
    with patch.object(subject, "pod_exec", return_value=output):
        facts = subject._pending_managed_push_facts(MagicMock())
    assert facts == " | ".join(
        [f"helper pid={pid}" for pid in range(1, 17)]
        + [f"lock owner_pid={pid}" for pid in range(1, 33)]
    )


def test_host_rejects_unrecognized_output() -> None:
    with patch.object(
        subject, "pod_exec", return_value="Authorization: Bearer private-secret"
    ):
        assert subject._pending_managed_push_facts(MagicMock()) == "unavailable"


@pytest.mark.parametrize(
    ("wchan", "expected_wait"),
    [
        ("pipe_read", "pipe_read"),
        ("locks_lock_inode_wait", "flock_wait"),
        ("folio_wait_bit_common", "file_io"),
        ("private-wchan-secret", "other"),
    ],
)
def test_generated_probe_filters_argv_and_emits_only_safe_process_facts(
    wchan: str,
    expected_wait: str,
) -> None:
    valid_argv = b"python\0-I\0-m\0onyx_guest\0push-managed\0private-metadata-secret\0"
    files: dict[str, bytes | str] = {
        "/proc/123/cmdline": valid_argv,
        "/proc/124/cmdline": b"python\0-c\0onyx_guest push-managed private-secret\0",
        "/proc/125/cmdline": b"python\0-m\0onyx_guest_other\0push-managed\0",
        "/proc/126/cmdline": b"python\0-m\0onyx_guest\0push-managed-other\0",
        "/proc/127/cmdline": valid_argv + b"x" * 4096,
        "/proc/123/stat": "123 (private-command-secret) S " + "0 " * 10 + "11 12\n",
        "/proc/123/wchan": wchan,
        "/proc/123/status": "Name: private-command-secret\nVmRSS: 64 kB\n",
        "/proc/meminfo": "MemTotal: 8192 kB\nMemAvailable: 4096 kB\nPrivate: secret\n",
        "/proc/locks": "1: FLOCK ADVISORY WRITE 123 00:2a:999 0 EOF\n1: -> FLOCK ADVISORY WRITE 124 00:2a:999 0 EOF\n2: FLOCK ADVISORY WRITE 125 00:2a:998 0 EOF\n3: POSIX ADVISORY WRITE 126 00:2a:999 0 EOF\n",
    }
    argv_reads: list[int] = []

    class ArgvSource(io.BytesIO):
        def read(self, size: int | None = -1, /) -> bytes:
            assert size == 4096
            argv_reads.append(size)
            return super().read(size)

    def open_file(path: Path, mode: str = "r") -> io.StringIO | io.BytesIO:
        content = files[str(path)]
        if mode == "rb":
            assert isinstance(content, bytes)
            return ArgvSource(content)
        assert isinstance(content, str)
        return io.StringIO(content)

    def stat_file(path: Path) -> os.stat_result:
        modes = {"0": stat.S_IFIFO, "1": stat.S_IFSOCK, "2": stat.S_IFCHR}
        if str(path) == "/run/onyx/managed.lock":
            return os.stat_result(
                (stat.S_IFREG, 999, os.makedev(0, 42), 1, 0, 0, 0, 0, 0, 0)
            )
        return os.stat_result((modes[path.name], 1, 1, 1, 0, 0, 0, 0, 0, 0))

    def probe(
        _client: object,
        _pod: str,
        _namespace: str,
        command: str,
        *,
        root: bool,
        timeout_s: float,
    ) -> str:
        argv = shlex.split(command)
        assert argv[:2] == ["python3", "-c"]
        assert len(argv) == 3
        assert root is True
        assert timeout_s == 5.0
        output = io.StringIO()
        with (
            patch.object(
                Path,
                "iterdir",
                return_value=iter(
                    [
                        Path("/proc/self"),
                        *(Path(f"/proc/{pid}") for pid in range(123, 128)),
                    ]
                ),
            ),
            patch.object(Path, "open", open_file),
            patch.object(Path, "stat", stat_file),
            patch("os.readlink", side_effect=AssertionError("readlink must not run")),
            patch("signal.alarm") as alarm,
            patch("sys.excepthook"),
            redirect_stdout(output),
        ):
            exec(argv[2], {})
        alarm.assert_called_once_with(5)
        assert "secret" not in output.getvalue()
        return output.getvalue()

    with patch.object(subject, "pod_exec", side_effect=probe):
        facts = subject._pending_managed_push_facts(MagicMock())
    assert facts == (
        "summary helper_count=1 total_kib=8192 available_kib=4096 | "
        f"helper pid=123 state=S utime_ticks=11 stime_ticks=12 wait={expected_wait} fd0=fifo fd1=socket fd2=char rss_kib=64 | "
        "lock owner_pid=123 | lock waiter_pid=124"
    )
    assert argv_reads == [4096] * 5


def test_generated_probe_stops_after_sixteen_helpers() -> None:
    opened_pids: list[int] = []

    def open_file(path: Path, mode: str = "r") -> io.StringIO | io.BytesIO:
        if path.name == "cmdline":
            assert mode == "rb"
            opened_pids.append(int(path.parent.name))
            return io.BytesIO(b"python\0-m\0onyx_guest\0push-managed\0")
        if path.name == "stat":
            return io.StringIO("123 (private-secret) R " + "0 " * 10 + "1 2\n")
        raise FileNotFoundError("private-secret")

    def probe(
        _client: object,
        _pod: str,
        _namespace: str,
        command: str,
        *,
        root: bool,
        timeout_s: float,
    ) -> str:
        assert (root, timeout_s) == (True, 5.0)
        script = shlex.split(command)[2]
        output = io.StringIO()
        with (
            patch.object(
                Path,
                "iterdir",
                return_value=iter(Path(f"/proc/{pid}") for pid in range(1, 21)),
            ),
            patch.object(Path, "open", open_file),
            patch.object(Path, "stat", side_effect=FileNotFoundError("private-secret")),
            patch("signal.alarm"),
            patch("sys.excepthook"),
            redirect_stdout(output),
        ):
            exec(script, {})
        assert "secret" not in output.getvalue()
        return output.getvalue()

    with patch.object(subject, "pod_exec", side_effect=probe):
        facts = subject._pending_managed_push_facts(MagicMock())
    assert opened_pids == list(range(1, 17))
    assert facts == " | ".join(
        ["summary helper_count=16"]
        + [
            f"helper pid={pid} state=R utime_ticks=1 stime_ticks=2 wait=other"
            for pid in range(1, 17)
        ]
    )


def test_root_sample_retains_existing_transport_timeout_allowance() -> None:
    workspace = subject.WorkspaceProxy(MagicMock(), "owned-user-b-pod")
    with patch("onyx.server.features.build.sandbox.exec.ExecClient") as client:
        client.return_value.run.return_value.stdout = b"summary helper_count=0\n"
        client.return_value.run.return_value.stderr = ""
        assert (
            subject._pending_managed_push_facts(workspace) == "summary helper_count=0"
        )
    client.assert_called_once_with(
        workspace._k8s_client.api_client.configuration, subject.SANDBOX_NAMESPACE
    )
    assert client.return_value.run.call_args.args[0] == "owned-user-b-pod"
    assert client.return_value.run.call_args.args[1][:2] == ["/bin/sh", "-c"]
    assert client.return_value.run.call_args.kwargs == {"stdin": None, "timeout": 20.0}
