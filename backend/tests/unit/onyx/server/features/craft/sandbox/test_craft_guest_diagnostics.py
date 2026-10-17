"""Craft timeout capture preserves the request error and private guest data."""

from __future__ import annotations

import io
import json
import os
import selectors
import stat
import subprocess
import sys
import time
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
                    "summary helper_count=0 metadata=private-secret target_sandbox_id=11111111-1111-1111-1111-111111111111\n",
                    "private-stderr",
                ),
            ],
        ) as run,
    ):
        assert subject._owned_guest_facts(ci_user, "kind-onyx-craft-ci") == (
            f"target_sandbox_id={_SANDBOX_ID} | summary helper_count=0"
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


def test_invalid_owned_sandbox_id_never_reaches_the_capture(
    ci_user: DATestUser, owned_sandbox: Sandbox
) -> None:
    with (
        patch.object(owned_sandbox, "id", "private-sandbox-secret"),
        patch.object(subject, "get_current_tenant_id", return_value="public"),
        patch.object(subject, "get_session_with_current_tenant"),
        patch.object(subject, "get_sandbox_by_user_id", return_value=owned_sandbox),
        patch.object(subject.subprocess, "run") as run,
        pytest.raises(ValueError),
    ):
        subject._owned_guest_facts(ci_user, "kind-onyx-craft-ci")
    run.assert_not_called()


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
        "summary helper_count=1 total_kib=8192 available_kib=4096 metadata=secret target_sandbox_id=private-secret\n"
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


@pytest.mark.parametrize(
    ("raw_fields", "expected"),
    [
        ("syscall=read syscall_fd=0", "syscall=read syscall_fd=0"),
        ("syscall=write syscall_fd=2", "syscall=write syscall_fd=2"),
        ("syscall=futex_wait syscall_fd=42", "syscall=futex_wait"),
        ("syscall=child_wait syscall_fd=42", "syscall=child_wait"),
        ("syscall=unavailable syscall_fd=0", "syscall=unavailable"),
        ("syscall=private-secret syscall_fd=0", ""),
        ("syscall_fd=0", ""),
        ("syscall=read syscall_fd=0x7fff12345678", "syscall=read"),
        ("syscall=read syscall_fd=2147483648", "syscall=read"),
        ("syscall=read syscall_fd=-1", "syscall=read"),
        ("syscall=read syscall_fd=１２３", "syscall=read"),
        ("syscall=read syscall_fd=private-secret", "syscall=read"),
    ],
)
def test_host_projects_only_bounded_io_descriptor_numbers(
    raw_fields: str, expected: str
) -> None:
    assert subject._managed_push_facts(f"helper pid=123 {raw_fields}") == (
        "helper pid=123" + (f" {expected}" if expected else "")
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
    ("wchan", "expected_wait", "syscall_snapshot", "machine", "expected_syscall"),
    [
        ("pipe_read", "pipe_read", "running", "x86_64", "unavailable"),
        ("anon_pipe_read", "pipe_read", "running", "x86_64", "unavailable"),
        ("fifo_pipe_read", "pipe_read", "running", "x86_64", "unavailable"),
        ("pipe_wait_readable", "pipe_read", "running", "x86_64", "unavailable"),
        ("futex_do_wait", "futex_wait", "running", "x86_64", "unavailable"),
        ("futex_sleep_multiple", "futex_wait", "running", "x86_64", "unavailable"),
        ("futex_wait_queue_me", "futex_wait", "running", "x86_64", "unavailable"),
        ("do_wait", "child_wait", "running", "x86_64", "unavailable"),
        ("kernel_wait4", "child_wait", "running", "x86_64", "unavailable"),
        ("locks_lock_inode_wait", "flock_wait", "running", "x86_64", "unavailable"),
        ("folio_wait_bit_common", "file_io", "running", "x86_64", "unavailable"),
        ("private-wchan-secret", "other", "running", "x86_64", "unavailable"),
        ("0", "other", "0 0x0", "x86_64", "unavailable"),
        ("0", "other", "0 0x0", "aarch64", "unavailable"),
        ("0", "other", "-1 0x7fff12345678 0x7fff12345678", "x86_64", "unavailable"),
        ("0", "other", "", "x86_64", "unavailable"),
        (
            "0",
            "other",
            PermissionError("private-syscall-secret"),
            "x86_64",
            "unavailable",
        ),
    ]
    + [
        (
            "0",
            "other",
            f"{number} {descriptor} 0x7fff12345678 0x1000 0x0 0x0 0x0 0x7fff12345678 0x7fff12345678",
            machine,
            expected,
        )
        for number, descriptor, machine, expected in [
            (0, "0x0", "x86_64", "read syscall_fd=0"),
            (1, "0x2", "x86_64", "write syscall_fd=2"),
            (19, "0x0", "x86_64", "read syscall_fd=0"),
            (20, "0x2", "x86_64", "write syscall_fd=2"),
            (202, "0x7fff12345678", "x86_64", "futex_wait"),
            (449, "0x7fff12345678", "x86_64", "futex_wait"),
            (455, "0x7fff12345678", "x86_64", "futex_wait"),
            (61, "0x1", "x86_64", "child_wait"),
            (247, "0x1", "x86_64", "child_wait"),
            (999, "0x7fff12345678", "x86_64", "other"),
            (-1, "0x0", "x86_64", "unavailable"),
            (0, "0x7fff12345678", "x86_64", "read"),
            (0, "private-secret", "x86_64", "read"),
            (0, "0x0", "aarch64", "unavailable"),
        ]
    ],
)
def test_generated_probe_filters_argv_and_emits_only_safe_process_facts(
    wchan: str,
    expected_wait: str,
    syscall_snapshot: str | OSError,
    machine: str,
    expected_syscall: str,
) -> None:
    valid_argv = b"python\0-I\0-m\0onyx_guest\0push-managed\0private-metadata-secret\0"
    files: dict[str, bytes | str | OSError] = {
        "/proc/123/cmdline": valid_argv,
        "/proc/124/cmdline": b"python\0-c\0onyx_guest push-managed private-secret\0",
        "/proc/125/cmdline": b"python\0-m\0onyx_guest_other\0push-managed\0",
        "/proc/126/cmdline": b"python\0-m\0onyx_guest\0push-managed-other\0",
        "/proc/127/cmdline": valid_argv + b"x" * 4096,
        "/proc/123/stat": "123 (private-command-secret) S " + "0 " * 10 + "11 12\n",
        "/proc/123/wchan": wchan,
        "/proc/123/syscall": syscall_snapshot,
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

    class SyscallSource(io.StringIO):
        def read(self, size: int | None = -1, /) -> str:
            assert size == 256
            return super().read(size)

    def open_file(path: Path, mode: str = "r") -> io.StringIO | io.BytesIO:
        content = files[str(path)]
        if isinstance(content, OSError):
            raise content
        if mode == "rb":
            assert isinstance(content, bytes)
            return ArgvSource(content)
        assert isinstance(content, str)
        if path.name == "syscall":
            assert machine == "x86_64"
            return SyscallSource(content)
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
            patch(
                "os.uname", return_value=os.uname_result(("Linux", "", "", "", machine))
            ),
            patch("signal.alarm") as alarm,
            patch("sys.excepthook"),
            redirect_stdout(output),
        ):
            exec(subject._MANAGED_PUSH_PROBE, {})
        alarm.assert_called_once_with(5)
        assert "secret" not in output.getvalue()
        assert "0x" not in output.getvalue()
        return output.getvalue()

    facts = subject._managed_push_facts(probe())
    assert facts == (
        "summary helper_count=1 total_kib=8192 available_kib=4096 | "
        f"helper pid=123 state=S utime_ticks=11 stime_ticks=12 wait={expected_wait} syscall={expected_syscall} fd0=fifo fd1=socket fd2=char rss_kib=64 | "
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
            f"helper pid={pid} state=R utime_ticks=1 stime_ticks=2 wait=other syscall=unavailable"
            for pid in range(1, 17)
        ]
    )


@pytest.mark.skipif(
    sys.platform != "linux" or os.uname().machine != "x86_64",
    reason="Requires native x86_64 Linux procfs",
)
def test_generated_probe_observes_owned_stdin_read_without_consuming_input() -> None:
    with subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'ready\\n'); os.write(1, os.read(0, 1))",
            "-m",
            "onyx_guest",
            "push-managed",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as helper:
        assert helper.stdin is not None
        assert helper.stdout is not None
        with selectors.DefaultSelector() as ready:
            ready.register(helper.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=5)
        assert helper.stdout.readline() == b"ready\n"
        deadline = time.monotonic() + 5
        facts = ""
        while time.monotonic() < deadline:
            output = io.StringIO()
            with (
                patch.object(
                    Path, "iterdir", return_value=iter([Path(f"/proc/{helper.pid}")])
                ),
                patch("signal.alarm"),
                patch("sys.excepthook"),
                redirect_stdout(output),
            ):
                exec(subject._MANAGED_PUSH_PROBE, {})
            facts = subject._managed_push_facts(output.getvalue())
            if "wait=pipe_read syscall=read syscall_fd=0 fd0=fifo" in facts:
                break
            time.sleep(0.01)
        assert f"helper pid={helper.pid} state=S" in facts
        assert "wait=pipe_read syscall=read syscall_fd=0 fd0=fifo" in facts
        helper.stdin.write(b"x")
        helper.stdin.flush()
        stdout, stderr = helper.communicate(timeout=5)
        assert stdout == b"x"
        assert stderr == b""
        assert helper.returncode == 0
