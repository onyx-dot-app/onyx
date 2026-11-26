"""The Firecracker smoke test script (scripts/craft_fc_smoke.py) against
Postgres, Redis and a fake host agent: every step passes on a working
deployment, a failed step skips the rest, and the cleanup always removes the
test user and the VM."""

import hashlib
import shlex
from collections.abc import Generator
from uuid import UUID

import pytest
from scripts import craft_fc_smoke as smoke
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheBackend
from onyx.db.sandbox import create_sandbox__no_commit
from onyx.db.users import (
    batch_add_ext_perm_user_if_not_exists,
    fetch_user_by_id,
    get_all_users,
)
from onyx.microvm.registry import get_sandbox_placement
from onyx.server.features.build.sandbox.firecracker import harness_state
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    get_session_save,
)
from onyx.server.features.build.sandbox.models import ExecCommandResult
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    forget_sandbox_keys,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    InsecureClientFactory,
    RunningFakeAgent,
)
from tests.external_dependency_unit.microvm.test_firecracker_session_saves import (
    FakeArchiveStore,
)


class FakeProbe:
    """The fake store keeps no file record: the object stands for both."""

    def __init__(self, node: RunningFakeAgent, file_id: str) -> None:
        self._node = node
        self._file_id = file_id

    def record_exists(self) -> bool:
        return self._file_id in self._node.agent.objects

    def object_status(self) -> int:
        return 200 if self._file_id in self._node.agent.objects else 404


def _result(output: str, exit_code: int = 0) -> ExecCommandResult:
    return ExecCommandResult(
        head=output,
        tail="",
        omitted_chars=0,
        session_id=None,
        exit_code=exit_code,
        completion="exited",
        wall_time_seconds=0.0,
        truncated=False,
    )


class FakeShell:
    """Answers the smoke script's shell commands from the fake agent's files:
    the fake daemon runs only scripted commands."""

    def __init__(self, node: RunningFakeAgent, uid: int = smoke.SANDBOX_UID) -> None:
        self.node = node
        self.uid = uid

    def __call__(self, test: smoke.FirecrackerSmoke, cmd: str) -> ExecCommandResult:
        key = (str(test.ref.sandbox_id), str(test.ref.session_id))
        files = self.node.agent.files
        if cmd.startswith("id -u"):
            return _result(f"{self.uid}\nsandbox\n")
        if cmd.startswith("sha256sum"):
            data = files[(*key, smoke.DATA_PATH)]
            files[(*key, smoke.NOTE_PATH)] = smoke.NOTE_TEXT.encode()
            digest = hashlib.sha256(data).hexdigest()
            return _result(f"{digest}  {smoke.DATA_PATH}\n{self.uid}\n")
        if cmd.startswith("curl"):
            return _result("200")
        if shlex.split(cmd)[:1] == ["cat"]:
            note = files.get((*key, smoke.NOTE_PATH), b"")
            return _result(note.decode())
        raise AssertionError(f"unexpected command {cmd!r}")


@pytest.fixture
def node(add_node: AddNode) -> RunningFakeAgent:
    return add_node("smoke-node")


@pytest.fixture
def harness(
    node: RunningFakeAgent,
    client_factory: InsecureClientFactory,
    tenant_cache: CacheBackend,
    db_session: Session,  # noqa: ARG001 - starts the SQL engine
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[FirecrackerHarnessSandbox, None, None]:
    sandbox = FirecrackerHarnessSandbox(
        template="tpl-1",
        client_factory=client_factory,
        archive_store=FakeArchiveStore(node),
    )
    monkeypatch.setattr(smoke, "FIRECRACKER_ENABLED", True)
    monkeypatch.setattr(smoke, "SANDBOX_FC_TEMPLATE", "tpl-1")
    monkeypatch.setattr(smoke, "get_firecracker_sandbox", lambda: sandbox)
    monkeypatch.setattr(smoke, "MtlsHostAgentClientFactory", lambda: client_factory)
    monkeypatch.setattr(smoke, "ArchiveProbe", lambda _t, f: FakeProbe(node, f))
    created: list[UUID] = []
    real_create = smoke.create_sandbox__no_commit

    def create(db: Session, user_id: UUID) -> object:
        row = real_create(db, user_id)
        created.append(row.id)
        return row

    monkeypatch.setattr(smoke, "create_sandbox__no_commit", create)
    yield sandbox
    for sandbox_id in created:
        forget_sandbox_keys(tenant_cache, sandbox_id)
        for prefix in harness_state.SANDBOX_STATE_PREFIXES:
            tenant_cache.delete(prefix + str(sandbox_id))


def _run(
    test: smoke.FirecrackerSmoke, monkeypatch: pytest.MonkeyPatch
) -> list[smoke.StepResult]:
    def idle() -> None:
        # As if no call asked for the sandbox recently.
        test.tenant_cache.delete(harness_state.WANTED_PREFIX + str(test.ref.sandbox_id))

    monkeypatch.setattr(smoke, "wait_for_idle", idle)
    return smoke.run_steps(test.steps(), ("cleanup", test.cleanup))


def _statuses(results: list[smoke.StepResult]) -> dict[str, smoke.StepStatus]:
    return {r.name: r.status for r in results}


def test_every_step_passes_and_the_cleanup_removes_user_and_vm(
    harness: FirecrackerHarnessSandbox,  # noqa: ARG001
    node: RunningFakeAgent,
    tenant_cache: CacheBackend,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke.FirecrackerSmoke, "_exec", lambda s, c: FakeShell(node)(s, c)
    )
    test = smoke.FirecrackerSmoke(TENANT_ID, smoke.DEFAULT_EGRESS_URL)

    results = _run(test, monkeypatch)

    assert [r.name for r in results] == [
        "create",
        "exec-uid",
        "file",
        "egress",
        "save-stop",
        "resume",
        "purge",
        "cleanup",
    ]
    assert all(r.status is smoke.StepStatus.PASS for r in results), results
    assert smoke.exit_code(results) == 0
    assert smoke.summary(results) == "RESULT PASS (8/8 steps passed)"
    assert test.user_id is not None and test.sandbox_id is not None
    assert fetch_user_by_id(db_session, test.user_id) is None
    assert get_sandbox_placement(tenant_cache, test.sandbox_id) is None
    assert get_session_save(tenant_cache, test.ref.session_id) is None
    assert test.file_id is not None and test.file_id not in node.agent.objects
    assert not any(k[0] == str(test.sandbox_id) for k in node.agent.files)


def test_a_failed_step_skips_the_rest_and_the_cleanup_still_runs(
    harness: FirecrackerHarnessSandbox,  # noqa: ARG001
    node: RunningFakeAgent,
    tenant_cache: CacheBackend,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke.FirecrackerSmoke, "_exec", lambda s, c: FakeShell(node, uid=0)(s, c)
    )
    test = smoke.FirecrackerSmoke(TENANT_ID, None)

    results = _run(test, monkeypatch)

    assert _statuses(results) == {
        "create": smoke.StepStatus.PASS,
        "exec-uid": smoke.StepStatus.FAIL,
        "file": smoke.StepStatus.SKIP,
        "save-stop": smoke.StepStatus.SKIP,
        "resume": smoke.StepStatus.SKIP,
        "purge": smoke.StepStatus.SKIP,
        "cleanup": smoke.StepStatus.PASS,
    }
    assert smoke.exit_code(results) == 1
    assert smoke.summary(results).startswith("RESULT FAIL")
    assert test.user_id is not None and test.sandbox_id is not None
    assert fetch_user_by_id(db_session, test.user_id) is None
    assert get_sandbox_placement(tenant_cache, test.sandbox_id) is None


def test_cleanup_leaked_removes_only_smoke_test_users(
    harness: FirecrackerHarnessSandbox,  # noqa: ARG001
    db_session: Session,
) -> None:
    leaked_email = smoke.smoke_email()
    other_email = f"{smoke.SMOKE_EMAIL_PREFIX}keep@other.example.org"
    by_email = {
        user.email: user.id
        for user in batch_add_ext_perm_user_if_not_exists(
            db_session, [leaked_email, other_email]
        )
    }
    leaked_id, other_id = by_email[leaked_email], by_email[other_email]
    create_sandbox__no_commit(db_session, leaked_id)
    db_session.commit()
    try:
        detail = smoke.cleanup_leaked(TENANT_ID)

        db_session.expire_all()
        assert fetch_user_by_id(db_session, leaked_id) is None
        assert fetch_user_by_id(db_session, other_id) is not None
        assert detail == "1 leaked test users removed"
    finally:
        smoke.delete_smoke_user(TENANT_ID, other_id)
    emails = {u.email for u in get_all_users(db_session, include_external=True)}
    assert leaked_email not in emails


def test_a_step_exception_becomes_a_failed_result() -> None:
    def broken() -> str:
        raise RuntimeError("agent down")

    results = smoke.run_steps([("create", broken)], ("cleanup", lambda: "ok"))

    assert [(r.name, r.status) for r in results] == [
        ("create", smoke.StepStatus.FAIL),
        ("cleanup", smoke.StepStatus.PASS),
    ]
    assert results[0].detail == "RuntimeError: agent down"
    assert smoke.format_result(results[0]).startswith("FAIL create")


@pytest.mark.parametrize(
    ("output", "code"),
    [("200", 200), ("curl: (6) Could not resolve host\n000", 0), ("", None)],
)
def test_parse_http_code(output: str, code: int | None) -> None:
    assert smoke.parse_http_code(output) == code
