"""Fixtures for build mode tests.

See ``docs/craft/test-master-plan.md`` Part V for the contract these fixtures
honour and the broader test layer model.
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
import time
import zipfile
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import TYPE_CHECKING
from uuid import UUID
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper

if TYPE_CHECKING:
    from kubernetes import client as k8s_client_module
from redis import Redis
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import AccountType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import Skill
from onyx.db.models import Skill__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserRole
from onyx.file_store.file_store import get_default_file_store
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.sandbox.base import ACPEvent
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.local.local_sandbox_manager import (
    LocalSandboxManager,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.session.manager import SessionManager
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import default_llm_config
from tests.external_dependency_unit.craft.stubs import StubSandboxManager

_DEV_PUSH_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


@pytest.fixture(autouse=True)
def _sandbox_push_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONYX_SANDBOX_PUSH_PRIVATE_KEY", _DEV_PUSH_KEY)


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Create a database session for testing using the actual PostgreSQL database."""
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    """Set up tenant context for testing."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def test_user(db_session: Session, tenant_context: None) -> User:  # noqa: ARG001
    """Create a test user for build session tests."""
    unique_email = f"build_test_{uuid4().hex[:8]}@example.com"

    password_helper = PasswordHelper()
    password = password_helper.generate()
    hashed_password = password_helper.hash(password)

    user = User(
        id=uuid4(),
        email=unique_email,
        hashed_password=hashed_password,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.EXT_PERM_USER,
        account_type=AccountType.EXT_PERM_USER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def build_session(
    db_session: Session,
    test_user: User,
    tenant_context: None,  # noqa: ARG001
) -> BuildSession:
    """Create a test build session."""
    session = BuildSession(
        id=uuid4(),
        user_id=test_user.id,
        name="Test Build Session",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


@pytest.fixture(scope="function")
def sandbox(
    db_session: Session,
    test_user: User,
    tenant_context: None,  # noqa: ARG001
) -> Callable[..., Sandbox]:
    """Factory: create a ``Sandbox`` row for a user.

    Default owner is ``test_user``; default status is RUNNING. Pass ``user`` or
    ``status`` to override. Multiple calls (with distinct users) yield distinct
    rows.
    """

    def _make(
        user: User | None = None,
        status: SandboxStatus = SandboxStatus.RUNNING,
    ) -> Sandbox:
        owner = user or test_user
        row = Sandbox(
            id=uuid4(),
            user_id=owner.id,
            status=status,
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row

    return _make


@pytest.fixture(scope="function")
def build_session_with_user(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
    tenant_context: None,  # noqa: ARG001
) -> Callable[..., BuildSession]:
    """Factory: create a ``BuildSession`` tied to a user (and optional sandbox).

    Distinct from the existing ``build_session`` fixture (which is a single
    row, not a factory) because tests in Part V want to create multiple
    sessions per test.
    """

    def _make(
        user: User | None = None,
        status: BuildSessionStatus = BuildSessionStatus.ACTIVE,
        provision_sandbox: bool = False,
        name: str | None = None,
    ) -> BuildSession:
        owner = user or test_user
        if provision_sandbox:
            sandbox(user=owner)
        session_row = BuildSession(
            id=uuid4(),
            user_id=owner.id,
            name=name or "Test Build Session",
            status=status,
        )
        db_session.add(session_row)
        db_session.commit()
        db_session.refresh(session_row)
        return session_row

    return _make


@dataclass(frozen=True)
class SandboxHandle:
    """Handle returned by the ``running_sandbox`` factory.

    Exposes the provisioned manager + IDs and resolves common workspace paths
    so call-sites stay short. Also supports ``provision_for(user)`` to add
    additional sandboxes for other users that share the same redirected
    ``SANDBOX_BASE_PATH`` and singleton manager — this is how the push-pipeline
    tests provision FS for the cohort returned by ``granted_users``.
    """

    manager: LocalSandboxManager
    sandbox_id: UUID
    session_id: UUID | None
    info: SandboxInfo
    base_path: Path
    # Required to provision additional sandboxes for other users.
    _db_session: Session
    _llm_config: LLMProviderConfig
    _register_extra: Callable[[UUID], None]

    @property
    def workspace_path(self) -> Path:
        return self.base_path / str(self.sandbox_id)

    @property
    def skills_path(self) -> Path:
        return self.workspace_path / "managed" / "skills"

    def provision_for(
        self, user: User, status: SandboxStatus = SandboxStatus.RUNNING
    ) -> tuple[Sandbox, Path]:
        """Create a Sandbox row for ``user``, provision its FS, return (row, workspace).

        Use this when a test needs more than one sandbox provisioned under the
        same redirected ``SANDBOX_BASE_PATH`` — e.g. push-pipeline tests that
        iterate over a cohort from ``granted_users``. The new sandbox is
        terminated on teardown via the same finalizer chain the fixture set up.

        If ``status`` is not RUNNING, the row is updated after provisioning
        (the manager always starts with RUNNING).
        """
        sandbox_row = Sandbox(
            id=uuid4(),
            user_id=user.id,
            status=SandboxStatus.RUNNING,
        )
        self._db_session.add(sandbox_row)
        self._db_session.commit()
        self._db_session.refresh(sandbox_row)

        self.manager.provision(
            sandbox_id=sandbox_row.id,
            user_id=user.id,
            tenant_id=TEST_TENANT_ID,
            llm_config=self._llm_config,
        )
        self._register_extra(sandbox_row.id)

        if status != SandboxStatus.RUNNING:
            sandbox_row.status = status
            self._db_session.commit()

        return sandbox_row, self.base_path / str(sandbox_row.id)


@pytest.fixture(scope="function")
def local_sandbox_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``LocalSandboxManager``'s base + template paths into ``tmp_path``.

    Patches:
      * ``SANDBOX_BASE_PATH`` in both the configs module and the manager
        module (the latter imports it by value at import time).
      * ``OUTPUTS_TEMPLATE_PATH`` / ``VENV_TEMPLATE_PATH`` so
        ``LocalSandboxManager._validate_templates()`` passes in CI / dev
        environments where the real template directories don't exist
        (they only ship inside the ``Dockerfile.sandbox-templates`` image).
      * ``LocalSandboxManager._instance`` AND ``base._sandbox_manager_instance``
        so the next ``LocalSandboxManager()`` / ``get_sandbox_manager()``
        constructs a fresh manager bound to these paths.

    ``raising=False`` on the singleton reset because the attribute may
    already be ``None`` when no previous test instantiated the manager.

    Returns the redirected base path so callers can compute workspace
    locations under it.
    """
    base_path = tmp_path / "sandboxes"
    base_path.mkdir(parents=True, exist_ok=True)
    outputs_tpl = tmp_path / "templates" / "outputs"
    venv_tpl = tmp_path / "templates" / "venv"
    outputs_tpl.mkdir(parents=True, exist_ok=True)
    venv_tpl.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "onyx.server.features.build.configs.SANDBOX_BASE_PATH",
        str(base_path),
    )
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.local.local_sandbox_manager.SANDBOX_BASE_PATH",
        str(base_path),
    )
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.local.local_sandbox_manager.OUTPUTS_TEMPLATE_PATH",
        str(outputs_tpl),
    )
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.local.local_sandbox_manager.VENV_TEMPLATE_PATH",
        str(venv_tpl),
    )
    monkeypatch.setattr(LocalSandboxManager, "_instance", None, raising=False)
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.base._sandbox_manager_instance",
        None,
    )

    return base_path


@pytest.fixture(scope="function")
def running_sandbox(
    db_session: Session,
    test_user: User,
    tenant_context: None,  # noqa: ARG001
    request: pytest.FixtureRequest,
    local_sandbox_paths: Path,
) -> Callable[..., SandboxHandle]:
    """Factory: provision a real sandbox via ``LocalSandboxManager``.

    Each call provisions a fresh sandbox under the tmp ``SANDBOX_BASE_PATH``
    set up by ``local_sandbox_paths``. Teardown is LIFO via
    ``request.addfinalizer``.
    """
    base_path = local_sandbox_paths

    # Track extra sandboxes provisioned via SandboxHandle.provision_for so
    # teardown can terminate them too.
    extra_sandbox_ids: list[UUID] = []

    def _register_extra(sandbox_id: UUID) -> None:
        extra_sandbox_ids.append(sandbox_id)

    def _make(
        user: User | None = None,
        llm_config: LLMProviderConfig | None = None,
        with_session: bool = False,
    ) -> SandboxHandle:
        owner = user or test_user
        config = llm_config or LLMProviderConfig(
            provider="openai",
            model_name="gpt-4",
            api_key="test-key",
            api_base=None,
        )

        sandbox_row = Sandbox(
            id=uuid4(),
            user_id=owner.id,
            status=SandboxStatus.RUNNING,
        )
        db_session.add(sandbox_row)
        db_session.commit()
        db_session.refresh(sandbox_row)

        # Force a brand-new singleton bound to the redirected base path. The
        # monkeypatch above restores the prior class attribute on teardown.
        LocalSandboxManager._instance = None
        manager = LocalSandboxManager()

        info = manager.provision(
            sandbox_id=sandbox_row.id,
            user_id=owner.id,
            tenant_id=TEST_TENANT_ID,
            llm_config=config,
        )

        session_id: UUID | None = None
        if with_session:
            session_row = BuildSession(
                id=uuid4(),
                user_id=owner.id,
                name="running-sandbox-session",
                status=BuildSessionStatus.ACTIVE,
            )
            db_session.add(session_row)
            db_session.commit()
            db_session.refresh(session_row)
            session_id = session_row.id

            manager.setup_session_workspace(
                sandbox_id=sandbox_row.id,
                session_id=session_id,
                llm_config=config,
                nextjs_port=None,
                skills_section="No skills available.",
            )

        # LIFO teardown: terminate sandbox + any extras added via
        # SandboxHandle.provision_for, then delete the primary DB row.
        def _cleanup() -> None:
            for extra_id in extra_sandbox_ids:
                try:
                    manager.terminate(extra_id)
                except (FileNotFoundError, OSError):
                    pass
            try:
                manager.terminate(sandbox_row.id)
            except (FileNotFoundError, OSError):
                # The workspace directory may already be gone if the test
                # tore it down explicitly. Any other exception is a real bug
                # and must propagate.
                pass
            existing = db_session.get(Sandbox, sandbox_row.id)
            if existing is not None:
                db_session.delete(existing)
                db_session.commit()

        request.addfinalizer(_cleanup)

        return SandboxHandle(
            manager=manager,
            sandbox_id=sandbox_row.id,
            session_id=session_id,
            info=info,
            base_path=base_path,
            _db_session=db_session,
            _llm_config=config,
            _register_extra=_register_extra,
        )

    return _make


@pytest.fixture(scope="function")
def granted_users(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Callable[..., dict[str, list[User]]]:
    """Factory: create users + sandboxes + groups in one call.

    Example
    -------
    ::

        cohort = granted_users(grants={"engineering": [None, None], "ops": [None]})

    Each value in the grants dict is interpreted as a list whose **length** is
    the number of users to create for that group. The factory creates the
    group if missing, creates fresh users for each slot, creates a sandbox per
    user (status=RUNNING), and links users to the group. Returns the
    realised mapping of group name → list of users.
    """
    password_helper = PasswordHelper()

    def _make(grants: dict[str, list[User | None]]) -> dict[str, list[User]]:
        out: dict[str, list[User]] = {}
        for group_name, slots in grants.items():
            group = (
                db_session.query(UserGroup)
                .filter(UserGroup.name == group_name)
                .one_or_none()
            )
            if group is None:
                group = UserGroup(
                    name=group_name,
                    is_up_to_date=True,
                    is_up_for_deletion=False,
                    is_default=False,
                )
                db_session.add(group)
                db_session.commit()
                db_session.refresh(group)

            created: list[User] = []
            for existing_user in slots:
                if existing_user is not None:
                    user = existing_user
                else:
                    password = password_helper.generate()
                    user = User(
                        id=uuid4(),
                        email=f"granted_{uuid4().hex[:8]}@example.com",
                        hashed_password=password_helper.hash(password),
                        is_active=True,
                        is_superuser=False,
                        is_verified=True,
                        role=UserRole.EXT_PERM_USER,
                        account_type=AccountType.EXT_PERM_USER,
                    )
                    db_session.add(user)
                    db_session.commit()
                    db_session.refresh(user)

                # One sandbox per user (status=RUNNING) — the docs say
                # "creates N users + sandboxes + group memberships".
                sandbox_row = Sandbox(
                    id=uuid4(),
                    user_id=user.id,
                    status=SandboxStatus.RUNNING,
                )
                db_session.add(sandbox_row)

                membership = User__UserGroup(
                    user_id=user.id,
                    user_group_id=group.id,
                    is_curator=False,
                )
                db_session.add(membership)

                created.append(user)

            db_session.commit()
            out[group_name] = created
        return out

    return _make


def _build_zip(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(path, data)
    return buf.getvalue()


@pytest.fixture(scope="function")
def seeded_bundle() -> Callable[[dict[str, bytes | str]], bytes]:
    """Pure utility: pack a dict of paths → contents into a zip bundle.

    Returns the bytes; the caller decides where to put them.
    """
    return _build_zip


@pytest.fixture(scope="function")
def seeded_skill(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Callable[..., Skill]:
    """Factory: create a ``Skill`` row + its bundle in the file store.

    Convenience wrapper over the admin-skills create path. Tests that exercise
    the HTTP boundary should still go through the admin API; this factory is
    for tests that need a Skill row to be **present** without making HTTP
    calls.
    """
    file_store = get_default_file_store()
    file_store.initialize()

    def _make(
        slug: str,
        public: bool = False,
        groups: Iterable[UserGroup] | None = None,
        bundle_files: dict[str, bytes | str] | None = None,
        author_user_id: UUID | None = None,
    ) -> Skill:
        if bundle_files is None:
            bundle_files = {
                "SKILL.md": (
                    f"---\nname: {slug}\ndescription: Seeded skill {slug}\n---\n"
                ),
            }
        bundle_bytes = _build_zip(bundle_files)
        bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()

        bundle_file_id = file_store.save_file(
            content=io.BytesIO(bundle_bytes),
            display_name=f"{slug}.zip",
            file_origin=FileOrigin.SKILL_BUNDLE,
            file_type="application/zip",
        )

        skill = Skill(
            id=uuid4(),
            slug=slug,
            name=slug,
            description=f"Seeded skill {slug}",
            bundle_file_id=bundle_file_id,
            bundle_sha256=bundle_sha256,
            is_public=public,
            enabled=True,
            author_user_id=author_user_id,
        )
        db_session.add(skill)
        db_session.commit()
        db_session.refresh(skill)

        for group in groups or []:
            db_session.add(Skill__UserGroup(skill_id=skill.id, user_group_id=group.id))
        db_session.commit()
        return skill

    return _make


@pytest.fixture(scope="function")
def stub_sandbox_manager() -> StubSandboxManager:
    """Return a fresh ``StubSandboxManager`` per test."""
    return StubSandboxManager()


@pytest.fixture(scope="function")
def failing_sandbox_manager() -> Callable[..., StubSandboxManager]:
    """Factory variant: pre-configure a stub with a failure-injection map.

    Example
    -------
    ::

        stub = failing_sandbox_manager(
            fail_on={sandbox_id: FatalWriteError("nope")}
        )
    """

    def _make(
        fail_on: dict[UUID, Exception] | None = None,
    ) -> StubSandboxManager:
        stub = StubSandboxManager()
        if fail_on is not None:
            stub.write_files_to_sandbox_raises_for = dict(fail_on)
        return stub

    return _make


@pytest.fixture(scope="function")
def session_manager_with_stub(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    stub_sandbox_manager: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> SessionManager:
    """``SessionManager`` bound to the stub sandbox backend.

    Patches both ``session.manager.get_sandbox_manager`` (which
    ``SessionManager.__init__`` captures into ``self._sandbox_manager`` at
    construction time) AND ``sandbox.base._sandbox_manager_instance`` so any
    deferred lookup also lands on the stub. The LLM provider lookup is
    short-circuited to ``default_llm_config()`` so tests don't need a real
    provider configured in the DB.
    """
    monkeypatch.setattr(
        "onyx.server.features.build.session.manager.get_sandbox_manager",
        lambda: stub_sandbox_manager,
    )
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.base._sandbox_manager_instance",
        stub_sandbox_manager,
    )
    sm = SessionManager(db_session)
    monkeypatch.setattr(
        sm,
        "_get_llm_config",
        lambda *args, **kwargs: default_llm_config(),  # noqa: ARG005
    )
    # Sanity: SessionManager captured the stub at construction.
    assert sm._sandbox_manager is stub_sandbox_manager
    return sm


def assert_lock_serializes_two_threads(
    redis_client: Redis | TenantRedisClient,  # type: ignore[type-arg]
    lock_key: str,
    *,
    acquire_fn: Callable[[], Any] | None = None,  # noqa: ARG001
) -> None:
    """Verify two concurrent acquirers contend on ``lock_key`` — one waits.

    Spawns two threads that race for the same Redis lock; the first
    thread acquires + holds, the second observes that a non-blocking
    acquire fails (the serialization point). Cleans the key before and
    after.

    ``acquire_fn`` is accepted for API parity with future variants that
    may wrap a production acquire helper; the current implementation
    always uses ``redis_client.lock(lock_key)`` so the test pins the same
    contract that ``create_session_with_lock`` / ``provision_with_lock``
    rely on.
    """
    redis_client.delete(lock_key)

    first_holds_lock = threading.Event()
    release_event = threading.Event()
    second_saw_lock_held: list[bool] = []

    def first() -> None:
        lock = redis_client.lock(lock_key, timeout=30)
        assert lock.acquire(blocking=True, blocking_timeout=5) is True
        first_holds_lock.set()
        try:
            release_event.wait(timeout=5)
        finally:
            lock.release()

    def second() -> None:
        assert first_holds_lock.wait(timeout=5)
        lock = redis_client.lock(lock_key, timeout=30)
        acquired_immediately = lock.acquire(blocking=False)
        second_saw_lock_held.append(not acquired_immediately)
        if acquired_immediately:
            lock.release()
            return
        release_event.set()
        assert lock.acquire(blocking=True, blocking_timeout=5) is True
        lock.release()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert second_saw_lock_held == [True]
    redis_client.delete(lock_key)


@pytest.fixture(scope="function")
def acp_event_sequence() -> Callable[[Iterable[ACPEvent]], list[ACPEvent]]:
    """Helper: materialise an iterable of ACP events into a re-driveable list.

    Returns a fresh ``list[ACPEvent]`` suitable for assignment to
    ``stub.send_message_events``. The stub snapshots the list on assignment
    so the same stub can be re-driven across multiple ``send_message`` calls;
    materialising here ensures generators are not exhausted before assignment
    either.
    """

    def _make(events: Iterable[ACPEvent]) -> list[ACPEvent]:
        return list(events)

    return _make


# ---------------------------------------------------------------------------
# Kubernetes helpers (Part V.1)
#
# These are imported by the K8s-only test modules (test_kubernetes_sandbox.py,
# test_snapshot_restore.py). They never run under the local backend because
# the consumers gate execution behind a module-level ``pytestmark`` that
# skips when SANDBOX_BACKEND != KUBERNETES. The helpers are defined at module
# scope here so they can be imported as top-level callables.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def k8s_client() -> "k8s_client_module.CoreV1Api":
    """Session-scope CoreV1Api client.

    Only meaningful inside tests gated by
    ``pytest.mark.skipif(SANDBOX_BACKEND != KUBERNETES, ...)``. The fixture
    itself does not enforce that gate — module-level ``pytestmark`` does.
    """
    from kubernetes import client as k8s_client_module

    from onyx.server.features.build.sandbox.kubernetes.k8s_client import (
        load_kube_config,
    )

    load_kube_config()
    return k8s_client_module.CoreV1Api()


def pod_exec(
    client: "k8s_client_module.CoreV1Api",
    pod_name: str,
    namespace: str,
    command: str | list[str],
    container: str = "sandbox",
) -> str:
    """Run a one-shot command in a pod container; return combined output.

    Defaults to the ``sandbox`` container. Pass ``container="sidecar"`` for
    operations that need to write to ``/workspace/managed/`` (read-only in
    the sandbox container) or inspect the sidecar's environment.

    ``command`` may be a shell-string (auto-wrapped in ``/bin/sh -c``) or an
    explicit argv list passed straight through to ``connect_get_namespaced_pod_exec``.
    """
    from kubernetes.stream import stream as k8s_stream

    argv = ["/bin/sh", "-c", command] if isinstance(command, str) else list(command)
    resp = k8s_stream(
        client.connect_get_namespaced_pod_exec,
        name=pod_name,
        namespace=namespace,
        container=container,
        command=argv,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
    )
    return str(resp) if resp is not None else ""


def wait_for_nextjs_ready(
    client: "k8s_client_module.CoreV1Api",
    pod_name: str,
    port: int,
    max_attempts: int = 30,
) -> None:
    """Poll an in-pod Next.js server until it returns 200/304 on ``/``.

    Raises ``RuntimeError`` if the server is not ready after ``max_attempts``
    attempts (2-second sleeps between attempts).
    """
    script = (
        f"curl -s -o /dev/null -w '%{{http_code}}' "
        f"http://localhost:{port}/ 2>/dev/null || echo 'failed'"
    )
    for _attempt in range(max_attempts):
        resp = pod_exec(client, pod_name, SANDBOX_NAMESPACE, script)
        if resp and resp.strip() in ("200", "304"):
            return
        time.sleep(2)
    raise RuntimeError(
        f"Next.js server on pod {pod_name}:{port} not ready after "
        f"{max_attempts} attempts"
    )


def wait_for_pod_deletion(
    client: "k8s_client_module.CoreV1Api",
    pod_name: str,
    namespace: str = SANDBOX_NAMESPACE,
    max_attempts: int = 30,
) -> None:
    """Wait until the pod is fully gone (404) or in a terminating state."""
    from kubernetes.client.rest import ApiException

    for _ in range(max_attempts):
        try:
            pod = client.read_namespaced_pod(name=pod_name, namespace=namespace)
            if pod.metadata.deletion_timestamp is not None:
                time.sleep(1)
                continue
            time.sleep(1)
        except ApiException as e:
            if e.status == 404:
                return
            raise
    raise RuntimeError(
        f"Pod {pod_name} in namespace {namespace} was not deleted "
        f"after {max_attempts} attempts"
    )


# ---------------------------------------------------------------------------
# K8s shared fixtures (canonical home for k8s_manager + live_pod).
#
# Both fixtures previously lived (duplicated) in test_kubernetes_sandbox.py
# and test_snapshot_restore.py. Centralising them here lets each K8s test
# module just consume the fixture by name. Modules still set their own
# ``pytestmark = pytest.mark.skipif(SANDBOX_BACKEND != KUBERNETES, ...)`` —
# the fixtures themselves do not gate.
#
# We don't use the test_kubernetes_sandbox.py ``_is_kubernetes_available``
# call here — the cluster check happens implicitly when ``k8s_client`` or
# the manager makes its first API call.
# ---------------------------------------------------------------------------


_K8S_TEST_USER_ID = UUID("ee0dd46a-23dc-4128-abab-6712b3f4464c")


@pytest.fixture(scope="function")
def k8s_manager() -> Generator[KubernetesSandboxManager, None, None]:
    """Initialise DB engine + tenant context and return the K8s manager.

    Consumer modules must gate themselves on
    ``SANDBOX_BACKEND == KUBERNETES`` via ``pytestmark``.
    """
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield KubernetesSandboxManager()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def live_pod(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[tuple[UUID, UUID, str], None, None]:
    """Provision a sandbox + session pod and tear it down on exit.

    Yields ``(sandbox_id, session_id, pod_name)``. The pod is gated for
    health via a 15-attempt poll on ``manager.health_check``; if the pod
    never becomes healthy the fixture raises ``RuntimeError`` so the test
    fails fast rather than running against a half-baked sandbox.
    """
    sandbox_id = uuid4()
    session_id = uuid4()
    llm_config = default_llm_config(
        api_key=os.environ.get("OPENAI_API_KEY", "test-key"),
    )

    info = k8s_manager.provision(
        sandbox_id=sandbox_id,
        user_id=_K8S_TEST_USER_ID,
        tenant_id=TEST_TENANT_ID,
        llm_config=llm_config,
        onyx_pat="ci-test-pat",
    )
    assert info.status == SandboxStatus.RUNNING

    for _ in range(15):
        if k8s_manager.health_check(sandbox_id, timeout=5.0):
            break
        time.sleep(2)
    else:
        raise RuntimeError(f"Sandbox {sandbox_id} never became healthy")

    k8s_manager.setup_session_workspace(
        sandbox_id=sandbox_id,
        session_id=session_id,
        llm_config=llm_config,
        nextjs_port=None,
        skills_section="No skills available.",
    )

    pod_name = k8s_manager._get_pod_name(sandbox_id)

    try:
        yield sandbox_id, session_id, pod_name
    finally:
        try:
            k8s_manager.terminate(sandbox_id)
        except Exception:
            pass
        wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)
