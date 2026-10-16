"""Craft timeout capture preserves the request error and private guest data."""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from types import TracebackType
from typing import cast
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest

from onyx.db.models import Sandbox
from onyx.server.features.skill.models import SkillResponse
from tests.integration.common_utils import craft_guest_diagnostics as subject
from tests.integration.common_utils.http_client import set_test_client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.test_models import DATestUser

_USER_ID = UUID("6ea3cd96-725b-4217-98eb-4578cc80365e")
_SANDBOX_ID = UUID("3e65cb5e-c1dd-4315-b640-e89c05845218")
_POD_NAME = f"sandbox-{_SANDBOX_ID.hex}"
_SKILL = SkillResponse(
    id=UUID("1dacbd1c-3527-4588-804d-3fa75a593ebb"),
    source="custom",
    name="diagnostic-test",
    description="diagnostic test",
    enabled=False,
    can_toggle=True,
)


@pytest.fixture
def ci_user(monkeypatch: pytest.MonkeyPatch) -> DATestUser:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SANDBOX_TEST_KUBE_CONTEXT", "kind-onyx-craft-ci")
    monkeypatch.setenv("SANDBOX_TEST_FIRECRACKER", "true")
    monkeypatch.setenv("SANDBOX_TEST_FRONTEND_URL", "http://127.0.0.1:3000")
    monkeypatch.setattr(subject, "CRAFT_SANDBOX_RUNTIME", "kubernetes_firecracker")
    return DATestUser(
        id=str(_USER_ID),
        email="diagnostic@example.com",
        password="private-password",
        headers={"Authorization": "Bearer private-token"},
        cookies={"session": "private-cookie"},
        is_admin=False,
        is_active=True,
    )


@pytest.mark.parametrize("boundary", ["initial_post", "second_post", "skill_put"])
def test_read_timeout_captures_once_before_teardown_and_preserves_request(
    boundary: str, ci_user: DATestUser, capsys: pytest.CaptureFixture[str]
) -> None:
    original_error = httpx.ReadTimeout("request-secret")
    events: list[str] = []
    requests: list[httpx.Request] = []
    original_traceback: TracebackType | None = None

    def request(request: httpx.Request) -> httpx.Response:
        nonlocal original_traceback
        requests.append(request)
        events.append(request.method)
        if boundary != "second_post" or len(requests) == 3:
            try:
                raise original_error
            except httpx.ReadTimeout as error:
                original_traceback = error.__traceback__
                raise
        return httpx.Response(200, json={"id": "pre-existing-session"})

    def capture(user: DATestUser, context: str) -> str:
        assert user is ci_user
        assert context == "kind-onyx-craft-ci"
        events.append("capture")
        return "summary helper_count=0"

    with (
        httpx.Client(transport=httpx.MockTransport(request)) as active_client,
        patch.object(subject, "_owned_guest_facts", side_effect=capture) as sample,
    ):
        set_test_client(active_client)
        try:
            with pytest.raises(httpx.ReadTimeout) as raised:
                if boundary == "skill_put":
                    SkillManager.set_enabled(
                        _SKILL, ci_user, True, replace_conflict=True
                    )
                else:
                    BuildSessionManager.create(
                        ci_user, headless=False, name="private-name"
                    )
        finally:
            events.append("teardown")
            set_test_client(None)
    assert raised.value is original_error
    tracebacks = []
    traceback = raised.value.__traceback__
    while traceback is not None:
        tracebacks.append(traceback)
        traceback = traceback.tb_next
    assert original_traceback is tracebacks[-1]
    sample.assert_called_once_with(ci_user, "kind-onyx-craft-ci")
    assert events == (
        ["POST", "DELETE", "POST", "capture", "teardown"]
        if boundary == "second_post"
        else ["PUT" if boundary == "skill_put" else "POST", "capture", "teardown"]
    )
    for sent in requests:
        assert sent.headers["authorization"] == "Bearer private-token"
        if sent.method == "PUT":
            assert sent.url.path == f"/skills/{_SKILL.id}/enabled"
            assert json.loads(sent.content) == {
                "enabled": True,
                "replace_conflict": True,
            }
        else:
            assert sent.headers["cookie"] == "session=private-cookie"
            if sent.method == "POST":
                assert sent.url.path == "/build/sessions"
                assert json.loads(sent.content) == {
                    "headless": False,
                    "name": "private-name",
                }
            else:
                assert sent.url.path == "/build/sessions/pre-existing-session"
    assert capsys.readouterr().out == (
        "Craft HTTP read timeout; managed_push_facts=summary helper_count=0\n"
    )


def test_fast_requests_preserve_results_without_a_sample(ci_user: DATestUser) -> None:
    session_body = {
        "id": "new-session",
        "user_id": ci_user.id,
        "name": None,
        "status": "active",
        "created_at": "2026-10-15T00:00:00Z",
        "last_activity_at": "2026-10-15T00:00:00Z",
        "nextjs_port": None,
        "sandbox": None,
        "artifacts": [],
        "sharing_scope": "private",
        "origin": "INTERACTIVE",
        "agent_provider": None,
        "agent_model": None,
        "skills_stale": False,
        "session_loaded_in_sandbox": True,
    }

    def request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=(
                {**_SKILL.model_dump(mode="json"), "enabled": True}
                if request.method == "PUT"
                else session_body
            ),
        )

    with (
        httpx.Client(transport=httpx.MockTransport(request)) as active_client,
        patch.object(subject, "_owned_guest_facts") as sample,
    ):
        set_test_client(active_client)
        try:
            assert BuildSessionManager.create(ci_user).id == "new-session"
            assert SkillManager.set_enabled(_SKILL, ci_user, True).enabled is True
        finally:
            set_test_client(None)
    sample.assert_not_called()


@pytest.mark.parametrize(
    "original_error",
    [
        RuntimeError("request-secret"),
        TimeoutError("request-secret"),
        httpx.ConnectTimeout("request-secret"),
        httpx.HTTPStatusError(
            "request-secret",
            request=httpx.Request("PUT", "http://testserver/skills"),
            response=httpx.Response(500),
        ),
    ],
)
@pytest.mark.parametrize("manager", ["session", "skill"])
def test_other_request_errors_propagate_without_capture(
    manager: str, original_error: Exception, ci_user: DATestUser
) -> None:
    def request(_request: httpx.Request) -> httpx.Response:
        raise original_error

    with (
        httpx.Client(transport=httpx.MockTransport(request)) as active_client,
        patch.object(subject, "_owned_guest_facts") as sample,
    ):
        set_test_client(active_client)
        try:
            with pytest.raises(type(original_error)) as raised:
                if manager == "session":
                    BuildSessionManager.create(ci_user)
                else:
                    SkillManager.set_enabled(_SKILL, ci_user, True)
        finally:
            set_test_client(None)
    assert raised.value is original_error
    sample.assert_not_called()


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("GITHUB_ACTIONS", ""),
        ("GITHUB_ACTIONS", "false"),
        ("SANDBOX_TEST_KUBE_CONTEXT", ""),
        ("SANDBOX_TEST_KUBE_CONTEXT", "kind-production"),
        ("SANDBOX_TEST_FIRECRACKER", "false"),
        ("SANDBOX_TEST_FRONTEND_URL", ""),
        ("CRAFT_SANDBOX_RUNTIME", "docker"),
        ("in_process_client", "http://testserver"),
    ],
)
def test_capture_guard_prevents_db_and_cluster_access(
    setting: str, value: str, ci_user: DATestUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    if setting == "CRAFT_SANDBOX_RUNTIME":
        monkeypatch.setattr(subject, setting, value)
    elif setting != "in_process_client":
        monkeypatch.setenv(setting, value)
    original_error = httpx.ReadTimeout("request-secret")
    with (
        httpx.Client(
            base_url=value if setting == "in_process_client" else ""
        ) as active_client,
        patch.object(subject, "get_session_with_current_tenant") as db,
        patch.object(subject.subprocess, "run") as run,
    ):
        set_test_client(active_client)
        try:
            with pytest.raises(httpx.ReadTimeout) as raised:
                with subject.capture_guest_facts_on_read_timeout(ci_user):
                    raise original_error
        finally:
            set_test_client(None)
    assert raised.value is original_error
    db.assert_not_called()
    run.assert_not_called()


@pytest.fixture
def owned_sandbox() -> Sandbox:
    return Sandbox(id=_SANDBOX_ID, user_id=_USER_ID)


@pytest.fixture
def pod() -> dict[str, dict[str, object]]:
    return {
        "metadata": {
            "name": _POD_NAME,
            "namespace": subject.SANDBOX_NAMESPACE,
            "uid": "current-pod-uid",
            "labels": {
                subject.LABEL_SANDBOX_ID: str(_SANDBOX_ID),
                subject.LABEL_TENANT_ID: "public",
                subject.LABEL_SANDBOX_PROTOCOL: subject.SANDBOX_PROTOCOL_VERSION,
                subject.LABEL_K8S_COMPONENT: subject.LABEL_K8S_COMPONENT_SANDBOX,
                subject.LABEL_K8S_MANAGED_BY: subject.LABEL_K8S_MANAGED_BY_ONYX,
            },
        },
        "spec": {
            "runtimeClassName": "kata-fc",
            "containers": [{"name": "sandbox"}],
            "initContainers": [{"name": "sandbox-firewall"}],
        },
    }


def test_owned_current_pod_is_the_only_bounded_exec_target(
    ci_user: DATestUser, owned_sandbox: Sandbox, pod: dict[str, dict[str, object]]
) -> None:
    with (
        patch.object(subject, "get_current_tenant_id", return_value="public"),
        patch.object(subject, "get_session_with_current_tenant") as db,
        patch.object(
            subject, "get_sandbox_by_user_id", return_value=owned_sandbox
        ) as lookup,
        patch.object(
            subject.subprocess,
            "run",
            side_effect=[
                subprocess.CompletedProcess([], 0, json.dumps(pod), "private-stderr"),
                subprocess.CompletedProcess(
                    [],
                    0,
                    "summary helper_count=0 metadata=private-secret\n",
                    "private-stderr",
                ),
            ],
        ) as run,
    ):
        assert subject._owned_guest_facts(ci_user, "kind-onyx-craft-ci") == (
            "summary helper_count=0"
        )
    lookup.assert_called_once_with(db.return_value.__enter__.return_value, _USER_ID)
    prefix = [
        "kubectl",
        "--context",
        "kind-onyx-craft-ci",
        "--namespace",
        subject.SANDBOX_NAMESPACE,
    ]
    assert run.call_args_list[0].args == (
        [*prefix, "get", "pod", _POD_NAME, "-o", "json"],
    )
    assert run.call_args_list[0].kwargs == {
        "capture_output": True,
        "text": True,
        "timeout": 5.0,
        "check": True,
    }
    assert run.call_args_list[1].args == (
        [
            *prefix,
            "exec",
            _POD_NAME,
            "-c",
            "sandbox",
            "--",
            "python3",
            "-c",
            subject._MANAGED_PUSH_PROBE,
        ],
    )
    assert run.call_args_list[1].kwargs == {
        "capture_output": True,
        "text": True,
        "timeout": 20.0,
        "check": True,
    }
    assert run.call_count == 2


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_wrong_sandbox_owner_never_reads_a_pod(
    missing: bool, ci_user: DATestUser, owned_sandbox: Sandbox
) -> None:
    owned_sandbox.user_id = UUID("b432c433-934e-47ce-8d12-0ee7bbaed41e")
    with (
        patch.object(subject, "get_current_tenant_id", return_value="public"),
        patch.object(subject, "get_session_with_current_tenant"),
        patch.object(
            subject,
            "get_sandbox_by_user_id",
            return_value=None if missing else owned_sandbox,
        ),
        patch.object(subject.subprocess, "run") as run,
    ):
        if missing:
            assert (
                subject._owned_guest_facts(ci_user, "kind-onyx-craft-ci")
                == "unavailable"
            )
        else:
            with pytest.raises(ValueError):
                subject._owned_guest_facts(ci_user, "kind-onyx-craft-ci")
    run.assert_not_called()


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("metadata", "name", "sandbox-short"),
        ("metadata", "namespace", "other"),
        ("metadata", "uid", ""),
        ("metadata", "deletionTimestamp", "now"),
        ("labels", subject.LABEL_SANDBOX_ID, "unknown-owner"),
        ("labels", subject.LABEL_TENANT_ID, "another-tenant"),
        ("labels", subject.LABEL_SANDBOX_PROTOCOL, "1"),
        ("labels", subject.LABEL_K8S_MANAGED_BY, "other"),
        ("labels", subject.LABEL_K8S_COMPONENT, "other"),
        ("spec", "runtimeClassName", "runc"),
        ("spec", "containers", [{"name": "sandbox"}, {"name": "sidecar"}]),
        ("spec", "initContainers", [{"name": "other"}]),
    ],
)
def test_nonconforming_pod_never_executes(
    section: str,
    field: str,
    value: object,
    ci_user: DATestUser,
    owned_sandbox: Sandbox,
    pod: dict[str, dict[str, object]],
) -> None:
    if section == "labels":
        labels = cast(dict[str, object], pod["metadata"]["labels"])
        labels[field] = value
    else:
        pod[section][field] = value
    with (
        patch.object(subject, "get_current_tenant_id", return_value="public"),
        patch.object(subject, "get_session_with_current_tenant"),
        patch.object(subject, "get_sandbox_by_user_id", return_value=owned_sandbox),
        patch.object(
            subject.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(pod)),
        ) as run,
        pytest.raises(ValueError),
    ):
        subject._owned_guest_facts(ci_user, "kind-onyx-craft-ci")
    assert run.call_count == 1


@pytest.mark.parametrize(
    ("sample_error", "expected_class"),
    [
        (RuntimeError("sample-message-secret"), "RuntimeError"),
        (
            subprocess.TimeoutExpired(
                ["private-argv-secret"],
                20,
                output="private-output",
                stderr="private-stderr",
            ),
            "TimeoutExpired",
        ),
        (
            subprocess.CalledProcessError(
                1,
                ["private-argv-secret"],
                output="private-output",
                stderr="private-stderr",
            ),
            "CalledProcessError",
        ),
        (
            type("private-class-secret\n", (Exception,), {})("private-secret"),
            "Exception",
        ),
    ],
)
def test_diagnostic_failure_prints_only_class_and_preserves_read_timeout(
    sample_error: Exception,
    expected_class: str,
    ci_user: DATestUser,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_error = httpx.ReadTimeout("request-secret")
    with (
        httpx.Client() as active_client,
        patch.object(subject, "_owned_guest_facts", side_effect=sample_error) as sample,
    ):
        set_test_client(active_client)
        try:
            with pytest.raises(httpx.ReadTimeout) as raised:
                with subject.capture_guest_facts_on_read_timeout(ci_user):
                    raise original_error
        finally:
            set_test_client(None)
    assert raised.value is original_error
    sample.assert_called_once()
    assert capsys.readouterr().out == (
        f"Craft timeout sample failed; exception={expected_class}\n"
    )


def test_broken_diagnostic_output_preserves_read_timeout(ci_user: DATestUser) -> None:
    original_error = httpx.ReadTimeout("request-secret")
    with (
        httpx.Client() as active_client,
        patch.object(
            subject, "_owned_guest_facts", return_value="summary helper_count=0"
        ),
        patch("builtins.print", side_effect=BrokenPipeError("output-secret")),
    ):
        set_test_client(active_client)
        try:
            with pytest.raises(httpx.ReadTimeout) as raised:
                with subject.capture_guest_facts_on_read_timeout(ci_user):
                    raise original_error
        finally:
            set_test_client(None)
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
    facts = subject._managed_push_facts(output)
    assert facts == (
        "summary helper_count=1 total_kib=8192 available_kib=4096 | "
        "helper pid=123 state=S wait=flock_wait utime_ticks=11 stime_ticks=12 fd0=fifo fd1=socket fd2=char rss_kib=64 | "
        "helper pid=124 | lock owner_pid=123 waiter_pid=124"
    )


def test_host_bounds_helper_lock_rows_and_raw_output() -> None:
    output = "\n".join(f"helper pid={pid}" for pid in range(1, 21))
    output += "\n" + "\n".join(f"lock owner_pid={pid}" for pid in range(1, 41))
    output += "\n" + "x" * 4096 + "\nsummary helper_count=1"
    facts = subject._managed_push_facts(output)
    assert facts == " | ".join(
        [f"helper pid={pid}" for pid in range(1, 17)]
        + [f"lock owner_pid={pid}" for pid in range(1, 33)]
    )


def test_host_rejects_unrecognized_output() -> None:
    assert (
        subject._managed_push_facts("Authorization: Bearer private-secret")
        == "unavailable"
    )


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

    def probe() -> str:
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
            exec(subject._MANAGED_PUSH_PROBE, {})
        alarm.assert_called_once_with(5)
        assert "secret" not in output.getvalue()
        return output.getvalue()

    facts = subject._managed_push_facts(probe())
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

    def probe() -> str:
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
            exec(subject._MANAGED_PUSH_PROBE, {})
        assert "secret" not in output.getvalue()
        return output.getvalue()

    facts = subject._managed_push_facts(probe())
    assert opened_pids == list(range(1, 17))
    assert facts == " | ".join(
        ["summary helper_count=16"]
        + [
            f"helper pid={pid} state=R utime_ticks=1 stime_ticks=2 wait=other"
            for pid in range(1, 17)
        ]
    )
