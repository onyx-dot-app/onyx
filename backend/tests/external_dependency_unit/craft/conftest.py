"""Fixtures for build mode tests.

See ``docs/craft/test-master-plan.md`` Part V for the contract these fixtures
honour and the broader test layer model.
"""

from __future__ import annotations

import hashlib
import io
import os
import shlex
import threading
import time
import zipfile
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from pathlib import PurePosixPath
from typing import Any
from typing import TYPE_CHECKING
from uuid import UUID
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper

if TYPE_CHECKING:
    from kubernetes import client as k8s_client_module
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import AccountType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
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


# ---------------------------------------------------------------------------
# Skill-table isolation
# ---------------------------------------------------------------------------
#
# These tests run against the shared ``public`` schema (``TEST_TENANT_ID ==
# "public"``) — the very schema a self-hosted / local dev deployment uses. The
# fixtures and helpers below commit ``Skill`` / ``ExternalApp`` rows directly
# and nothing rolled them back, so every committed row leaked into the
# developer's live craft skill list (and into the next test's view of the
# table). Tests also delete/mutate the migration-seeded built-in rows
# (``pptx``, ``image-generation``, ``company-search``), corrupting them for the
# live app.
#
# The ``_test_helpers`` contract states "the surrounding test owns transaction
# boundaries"; this autouse fixture is that boundary for the skill tables. It
# snapshots their committed state before each test and restores it afterward,
# so a run leaves these tables exactly as it found them (the canonical
# built-ins on a freshly-migrated DB).

# Parent -> child order (FKs all point child -> parent). Restore/insert in this
# order; delete in reverse so FK constraints stay satisfied.
_SKILL_ISOLATION_MODELS: tuple[type[Any], ...] = (
    Skill,
    Skill__UserGroup,
    ExternalApp,
    ExternalAppUserCredential,
)


def _skill_table_column_keys(model: type[Any]) -> list[str]:
    return [attr.key for attr in class_mapper(model).column_attrs]


def _skill_table_pk_keys(model: type[Any]) -> list[str]:
    return [col.key for col in class_mapper(model).primary_key]


def _snapshot_skill_tables(
    session: Session,
) -> dict[type[Any], list[dict[str, Any]]]:
    snapshot: dict[type[Any], list[dict[str, Any]]] = {}
    for model in _SKILL_ISOLATION_MODELS:
        keys = _skill_table_column_keys(model)
        snapshot[model] = [
            {key: getattr(row, key) for key in keys}
            for row in session.execute(select(model)).scalars().all()
        ]
    return snapshot


def _restore_skill_tables(
    session: Session, snapshot: dict[type[Any], list[dict[str, Any]]]
) -> None:
    # Delete rows created during the test (children first so FKs stay valid).
    for model in reversed(_SKILL_ISOLATION_MODELS):
        pk_keys = _skill_table_pk_keys(model)
        baseline_pks = {tuple(row[key] for key in pk_keys) for row in snapshot[model]}
        for row in session.execute(select(model)).scalars().all():
            if tuple(getattr(row, key) for key in pk_keys) not in baseline_pks:
                session.delete(row)
        session.flush()

    # Re-insert baseline rows the test deleted and restore any it mutated
    # (parents first). ``merge`` keys on PK: insert when absent, update when
    # present.
    for model in _SKILL_ISOLATION_MODELS:
        for row in snapshot[model]:
            session.merge(model(**row))
        session.flush()

    session.commit()


@pytest.fixture(autouse=True)
def _isolate_skill_tables(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[None, None, None]:
    """Restore the skill tables to their pre-test state (see note above).

    Shares the test's ``db_session`` so there is a single transaction holder —
    no second connection that could block on row locks the test still holds.
    """
    snapshot = _snapshot_skill_tables(db_session)
    yield
    # Drop any uncommitted state a failing/early-exiting test left open before
    # reconciling against the committed baseline.
    db_session.rollback()
    _restore_skill_tables(db_session, snapshot)


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


# ---------------------------------------------------------------------------
# Pod-aware workspace proxy
#
# Migrated tests inspect files inside provisioned sandboxes via a ``Path``-like
# interface. With the local backend gone, those paths live inside a pod — but
# the call sites still want to write ``workspace.exists()``,
# ``(workspace / "managed" / "skills" / slug / "SKILL.md").read_bytes()``,
# etc. ``WorkspaceProxy`` mirrors the subset of ``pathlib.Path`` semantics the
# craft tests actually use; everything else raises so misuse fails loudly.
#
# All file operations go through ``pod_exec`` against the ``sandbox`` container,
# matching how production sandbox file ops work (read/list use exec; the
# managed/ tree is RO from the sandbox container but the tests read from it,
# which is fine).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceProxy:
    """``Path``-shaped proxy for a sandbox pod's ``/workspace/<sandbox_id>``.

    Implements the subset of ``pathlib.Path`` used by craft external-dep tests:
    ``/``, ``exists``, ``is_file``, ``is_symlink``, ``resolve``, ``read_bytes``,
    ``read_text``, ``rglob('*')``, ``name``. Everything else raises.

    Construct via :meth:`SandboxHandle.provision_for` — never directly.
    """

    _k8s_client: "k8s_client_module.CoreV1Api"
    _pod_name: str
    _sandbox_id: UUID
    _rel_parts: tuple[str, ...] = field(default_factory=tuple)

    # The "absolute path" inside the pod that this proxy represents. We use
    # ``/workspace`` (the per-pod root) + sandbox-id segment so the production
    # path layout (``managed/skills/...``, ``sessions/<id>/...``) matches what
    # the tests already write. Note: in the k8s manager, ``/workspace/managed``
    # and ``/workspace/sessions`` are pod-scoped, NOT sandbox-id-scoped, so we
    # drop the sandbox_id prefix unlike the old local layout.
    @property
    def _abs_posix(self) -> str:
        return (
            "/workspace/" + "/".join(self._rel_parts)
            if self._rel_parts
            else "/workspace"
        )

    @property
    def name(self) -> str:
        return self._rel_parts[-1] if self._rel_parts else "workspace"

    def __truediv__(self, segment: str | "WorkspaceProxy") -> "WorkspaceProxy":
        if isinstance(segment, WorkspaceProxy):
            raise TypeError("Cannot join two WorkspaceProxy instances")
        new_parts = self._rel_parts + tuple(
            p for p in PurePosixPath(segment).parts if p
        )
        return WorkspaceProxy(
            _k8s_client=self._k8s_client,
            _pod_name=self._pod_name,
            _sandbox_id=self._sandbox_id,
            _rel_parts=new_parts,
        )

    def _exec(self, command: str) -> str:
        from kubernetes.stream import stream as k8s_stream

        resp = k8s_stream(
            self._k8s_client.connect_get_namespaced_pod_exec,
            name=self._pod_name,
            namespace=SANDBOX_NAMESPACE,
            container="sandbox",
            command=["/bin/sh", "-c", command],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        return str(resp) if resp is not None else ""

    def exists(self) -> bool:
        quoted = shlex.quote(self._abs_posix)
        # `test -e` returns true for files, dirs, and symlinks to anything.
        # We also accept dangling symlinks (`test -L`) so symlink presence
        # tests don't fall through to "missing" when the target is unset.
        out = self._exec(
            f"if [ -e {quoted} ] || [ -L {quoted} ]; then echo Y; else echo N; fi"
        )
        return "Y" in out

    def is_file(self) -> bool:
        out = self._exec(
            f"if [ -f {shlex.quote(self._abs_posix)} ]; then echo Y; else echo N; fi"
        )
        return "Y" in out

    def is_symlink(self) -> bool:
        out = self._exec(
            f"if [ -L {shlex.quote(self._abs_posix)} ]; then echo Y; else echo N; fi"
        )
        return "Y" in out

    def resolve(self) -> "WorkspaceProxy":
        """Best-effort symlink resolution via ``readlink -f``.

        Returned proxy points at the resolved absolute path. Tests use this
        only for symlink-target equality checks, so we return a proxy with
        the resolved path inlined as the ``_rel_parts`` tail.
        """
        out = self._exec(
            f"readlink -f {shlex.quote(self._abs_posix)} || echo {shlex.quote(self._abs_posix)}"
        )
        resolved = out.strip()
        # Strip the /workspace/ prefix if present; otherwise treat as absolute.
        # Split into individual segments either way so ``__truediv__`` and
        # ``_abs_posix`` produce correct results when callers continue to
        # navigate from the resolved proxy.
        if resolved.startswith("/workspace/"):
            rel = resolved[len("/workspace/") :]
        else:
            rel = resolved.lstrip("/")
        parts = tuple(p for p in rel.split("/") if p)
        return WorkspaceProxy(
            _k8s_client=self._k8s_client,
            _pod_name=self._pod_name,
            _sandbox_id=self._sandbox_id,
            _rel_parts=parts,
        )

    def read_bytes(self) -> bytes:
        import base64

        out = self._exec(
            f"base64 {shlex.quote(self._abs_posix)} 2>/dev/null || echo __MISSING__"
        )
        if "__MISSING__" in out:
            raise FileNotFoundError(self._abs_posix)
        return base64.b64decode(out.strip())

    def read_text(self) -> str:
        return self.read_bytes().decode("utf-8")

    def rglob(self, pattern: str) -> list["WorkspaceProxy"]:
        if pattern != "*":
            raise NotImplementedError(
                "WorkspaceProxy.rglob only supports '*' (used by craft tests)"
            )
        out = self._exec(
            f"find {shlex.quote(self._abs_posix)} -mindepth 1 2>/dev/null || true"
        )
        results: list[WorkspaceProxy] = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            # Each line is an absolute pod path; convert to ``_rel_parts``.
            if line.startswith("/workspace/"):
                rel = line[len("/workspace/") :]
            elif line == "/workspace":
                continue
            else:
                rel = line.lstrip("/")
            parts = tuple(p for p in rel.split("/") if p)
            results.append(
                WorkspaceProxy(
                    _k8s_client=self._k8s_client,
                    _pod_name=self._pod_name,
                    _sandbox_id=self._sandbox_id,
                    _rel_parts=parts,
                )
            )
        return results

    def __fspath__(self) -> str:
        return self._abs_posix

    def __str__(self) -> str:
        return self._abs_posix

    def __eq__(self, other: object) -> bool:
        if isinstance(other, WorkspaceProxy):
            return self._abs_posix == other._abs_posix
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._abs_posix)


@dataclass(frozen=True)
class SandboxHandle:
    """Handle returned by the ``running_sandbox`` factory.

    Exposes the provisioned manager + IDs and resolves common workspace paths
    so call-sites stay short. Also supports ``provision_for(user)`` to add
    additional sandboxes for other users (each gets its own pod), mirroring
    the way push-pipeline tests provision a cohort returned by
    ``granted_users``.
    """

    manager: KubernetesSandboxManager
    sandbox_id: UUID
    session_id: UUID | None
    info: SandboxInfo
    _k8s_client: "k8s_client_module.CoreV1Api"
    # Required to provision additional sandboxes for other users.
    _db_session: Session
    _llm_config: LLMProviderConfig
    _register_extra: Callable[[UUID], None]

    @property
    def workspace_path(self) -> WorkspaceProxy:
        return WorkspaceProxy(
            _k8s_client=self._k8s_client,
            _pod_name=self.manager._get_pod_name(self.sandbox_id),
            _sandbox_id=self.sandbox_id,
        )

    @property
    def skills_path(self) -> WorkspaceProxy:
        return self.workspace_path / "managed" / "skills"

    def provision_for(
        self, user: User, status: SandboxStatus = SandboxStatus.RUNNING
    ) -> tuple[Sandbox, WorkspaceProxy]:
        """Create a Sandbox row for ``user``, provision its pod, return (row, workspace).

        Each provisioned sandbox lives in its own pod (k8s pods are per-
        sandbox-id). The pod is torn down on test teardown via the registered
        finalizer chain.

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

        _provision_with_retry(
            self.manager,
            sandbox_id=sandbox_row.id,
            user_id=user.id,
            tenant_id=TEST_TENANT_ID,
            llm_config=self._llm_config,
        )
        self._register_extra(sandbox_row.id)

        if status != SandboxStatus.RUNNING:
            sandbox_row.status = status
            self._db_session.commit()

        workspace = WorkspaceProxy(
            _k8s_client=self._k8s_client,
            _pod_name=self.manager._get_pod_name(sandbox_row.id),
            _sandbox_id=sandbox_row.id,
        )
        return sandbox_row, workspace


def _wait_until_healthy(
    manager: KubernetesSandboxManager,
    sandbox_id: UUID,
    max_attempts: int = 15,
    timeout: float = 5.0,
) -> None:
    for _ in range(max_attempts):
        if manager.health_check(sandbox_id, timeout=timeout):
            return
        time.sleep(2)
    raise RuntimeError(f"Sandbox {sandbox_id} never became healthy")


def _provision_with_retry(
    manager: KubernetesSandboxManager,
    *,
    sandbox_id: UUID,
    user_id: UUID,
    tenant_id: str,
    llm_config: LLMProviderConfig,
    onyx_pat: str | None = "ci-test-pat",
) -> SandboxInfo:
    """Provision + wait-healthy with a one-shot retry on flake.

    kind under load occasionally times out the manager's
    ``_wait_for_pod_ready`` (cluster scheduling pressure, transient
    image-pull retries). When that happens we terminate the half-baked
    pod and try once more — fresh scheduling usually succeeds. Real
    deterministic failures still raise on the second try.
    """
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            info = manager.provision(
                sandbox_id=sandbox_id,
                user_id=user_id,
                tenant_id=tenant_id,
                llm_config=llm_config,
                onyx_pat=onyx_pat,
            )
            _wait_until_healthy(manager, sandbox_id)
            return info
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == 0:
                # Tear down the half-baked pod before retrying so the
                # second attempt starts from a clean slate.
                try:
                    manager.terminate(sandbox_id)
                except Exception:
                    pass
                continue
            raise
    # Unreachable — the loop either returns or raises — but type-checkers
    # complain without an explicit terminator.
    raise RuntimeError(
        f"provision retry exhausted for {sandbox_id}: {last_err}"
    ) from last_err


# ---------------------------------------------------------------------------
# Pool pod amortization
#
# Pod provisioning costs ~20s. With ~15 tests calling running_sandbox(), naive
# per-test provisioning would burn ~5 min of CI time on idle pod startup. The
# pool_pod fixture provisions exactly one pod per test module and lets each
# test reuse it via a fresh-session-id pattern + pre-test cleanup of the
# mutable workspace trees (managed/skills, managed/user_library, sessions/).
#
# Tests that need multiple distinct pods (cohort tests via
# ``SandboxHandle.provision_for``) still pay per-pod cost — those scenarios
# inherently require multiple pod identities, so amortization is impossible
# there. The savings come from amortizing the *primary* handle's pod.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PoolPod:
    sandbox_id: UUID
    pod_name: str
    manager: KubernetesSandboxManager
    k8s_client: "k8s_client_module.CoreV1Api"
    info: SandboxInfo


def _cleanup_pool_workspace(
    k8s_client: "k8s_client_module.CoreV1Api",
    pod_name: str,
) -> None:
    """Wipe mutable trees on the pool pod before the next test runs.

    ``managed/`` is read-only in the sandbox container but writable from the
    sidecar (see ``kubernetes_sandbox_manager._build_pod_spec``), so we exec
    via the sidecar for the skills + user_library subtrees. ``sessions/`` is
    on a shared emptyDir, writable from either container.
    """
    # managed/{skills,user_library} live under the RO mount — clean via sidecar.
    # ``find -mindepth 1 -delete`` removes only the directory's contents
    # (including dotfiles) without the ``.*`` glob expanding to ``.``/``..``.
    pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "find /workspace/managed/skills /workspace/managed/user_library "
        "-mindepth 1 -delete 2>/dev/null; true",
        container="sidecar",
    )
    # sessions/ is the per-session emptyDir tree.
    pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "find /workspace/sessions -mindepth 1 -delete 2>/dev/null; true",
        container="sandbox",
    )


@pytest.fixture(scope="module")
def _pool_pod(
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[_PoolPod, None, None]:
    """Module-scoped sandbox pod shared by all ``running_sandbox()`` calls.

    Yields a :class:`_PoolPod` whose ``sandbox_id`` is reused across every
    function-scoped ``running_sandbox()`` call in the module. The function
    fixture wipes mutable trees on entry, so each test sees a clean
    workspace.

    The DB row backing the pool sandbox is owned by a module-scoped "pool
    user". Tests that pass ``user=`` to ``running_sandbox()`` get the pool
    sandbox anyway (the kwarg is honored for back-compat but the primary
    pod's identity stays stable); tests that genuinely need a user-owned
    sandbox should use ``SandboxHandle.provision_for(user)`` instead.
    """
    from onyx.server.features.build.configs import SANDBOX_BACKEND
    from onyx.server.features.build.configs import SandboxBackend

    if SANDBOX_BACKEND != SandboxBackend.KUBERNETES:
        pytest.skip(
            "_pool_pod requires SANDBOX_BACKEND=kubernetes "
            "(run via pr-craft-k8s-tests.yml or against a local kind cluster)"
        )

    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    manager = KubernetesSandboxManager()

    password_helper = PasswordHelper()
    pool_user_id = uuid4()
    pool_sandbox_id = uuid4()
    pool_user_email = f"pool_{pool_user_id.hex[:8]}@example.com"

    # Create pool user + sandbox DB rows.
    with get_session_with_current_tenant() as session:
        pool_user = User(
            id=pool_user_id,
            email=pool_user_email,
            hashed_password=password_helper.hash(password_helper.generate()),
            is_active=True,
            is_superuser=False,
            is_verified=True,
            role=UserRole.EXT_PERM_USER,
            account_type=AccountType.EXT_PERM_USER,
        )
        session.add(pool_user)
        session.add(
            Sandbox(
                id=pool_sandbox_id,
                user_id=pool_user_id,
                status=SandboxStatus.RUNNING,
            )
        )
        session.commit()

    # Provision the pod once, with a one-shot retry on flake.
    pool_info = _provision_with_retry(
        manager,
        sandbox_id=pool_sandbox_id,
        user_id=pool_user_id,
        tenant_id=TEST_TENANT_ID,
        llm_config=default_llm_config(
            api_key=os.environ.get("OPENAI_API_KEY", "test-key"),
        ),
    )
    pod_name = manager._get_pod_name(pool_sandbox_id)

    try:
        yield _PoolPod(
            sandbox_id=pool_sandbox_id,
            pod_name=pod_name,
            manager=manager,
            k8s_client=k8s_client,
            info=pool_info,
        )
    finally:
        try:
            manager.terminate(pool_sandbox_id)
        except Exception:
            pass
        try:
            wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)
        except Exception:
            pass
        with get_session_with_current_tenant() as session:
            row = session.get(Sandbox, pool_sandbox_id)
            if row is not None:
                session.delete(row)
            user_row = session.get(User, pool_user_id)
            if user_row is not None:
                session.delete(user_row)
            session.commit()
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def running_sandbox(
    db_session: Session,
    test_user: User,
    tenant_context: None,  # noqa: ARG001
    request: pytest.FixtureRequest,
) -> Callable[..., SandboxHandle]:
    """Factory: hand out a ``SandboxHandle`` bound to the module pool pod.

    Each call returns a handle backed by the shared :func:`_pool_pod`. The
    function fixture wipes ``/workspace/managed/skills``,
    ``/workspace/managed/user_library``, and ``/workspace/sessions`` on the
    pool pod before yielding, so every test sees a clean slate without
    paying the ~20s pod-provisioning cost. See module docstring above
    ``_PoolPod`` for the amortization rationale.

    Migration history: this fixture previously bound to
    ``LocalSandboxManager`` against ``tmp_path``. With the local backend
    gone (see ``docs/craft/2026-05-21-nuke-local-sandbox-manager.md``), it
    now wraps a real ``KubernetesSandboxManager`` pool pod against the kind
    cluster. The fixture self-gates on ``SANDBOX_BACKEND == KUBERNETES`` and
    ``pytest.skip``s otherwise, so test files using this fixture can sit in
    the same directory as stub-backed tests without a module-level
    ``pytestmark``. Tests consuming it run in the K8s CI lane only
    (``pr-craft-k8s-tests.yml``).

    The ``user=`` kwarg on ``_make`` is accepted for source-compat but
    ignored — the pool pod is owned by a module-scoped pool user. Tests
    that need a user-owned sandbox should call
    ``SandboxHandle.provision_for(user)`` instead.
    """
    from onyx.server.features.build.configs import SANDBOX_BACKEND
    from onyx.server.features.build.configs import SandboxBackend

    if SANDBOX_BACKEND != SandboxBackend.KUBERNETES:
        pytest.skip(
            "running_sandbox fixture requires SANDBOX_BACKEND=kubernetes "
            "(run via pr-craft-k8s-tests.yml or against a local kind cluster)"
        )
    pool: _PoolPod = request.getfixturevalue("_pool_pod")

    # Pre-test cleanup of mutable trees on the pool pod.
    _cleanup_pool_workspace(pool.k8s_client, pool.pod_name)

    # Track per-test pods provisioned via SandboxHandle.provision_for so
    # teardown can terminate them. The pool pod itself is NOT terminated
    # here — that's the module fixture's job.
    extra_sandbox_ids: list[UUID] = []

    def _register_extra(sandbox_id: UUID) -> None:
        extra_sandbox_ids.append(sandbox_id)

    def _make(
        user: User | None = None,
        llm_config: LLMProviderConfig | None = None,
        with_session: bool = False,
    ) -> SandboxHandle:
        config = llm_config or default_llm_config(
            api_key=os.environ.get("OPENAI_API_KEY", "test-key"),
        )

        session_id: UUID | None = None
        if with_session:
            # Fresh session id per call — sessions are namespaced under the
            # pool pod's /workspace/sessions/{id}/, so multiple calls in the
            # same test don't collide.
            session_id = uuid4()
            session_row = BuildSession(
                id=session_id,
                user_id=(user or test_user).id,
                name="running-sandbox-session",
                status=BuildSessionStatus.ACTIVE,
            )
            db_session.add(session_row)
            db_session.commit()

            pool.manager.setup_session_workspace(
                sandbox_id=pool.sandbox_id,
                session_id=session_id,
                llm_config=config,
                nextjs_port=None,
                skills_section="No skills available.",
            )

        def _cleanup() -> None:
            for extra_id in extra_sandbox_ids:
                try:
                    pool.manager.terminate(extra_id)
                except Exception:
                    pass
            # Pool pod is NOT terminated; the module fixture owns its
            # lifecycle. We deliberately leave mutable trees in place — the
            # next test's pre-yield cleanup wipes them.

        request.addfinalizer(_cleanup)

        return SandboxHandle(
            manager=pool.manager,
            sandbox_id=pool.sandbox_id,
            session_id=session_id,
            info=pool.info,
            _k8s_client=pool.k8s_client,
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
# test_snapshot_restore.py, test_kubernetes_sandbox_file_ops.py). They never
# run against the deleted local backend — consumers gate execution behind a
# module-level ``pytestmark`` that skips when SANDBOX_BACKEND != KUBERNETES.
# The helpers are defined at module scope here so they can be imported as
# top-level callables.
# ---------------------------------------------------------------------------


def _load_kube_config() -> None:
    """Load in-cluster config if available, otherwise fall back to kubeconfig."""
    from kubernetes import config as k8s_config_module

    try:
        k8s_config_module.load_incluster_config()
    except k8s_config_module.ConfigException:
        k8s_config_module.load_kube_config()


@pytest.fixture(scope="session")
def k8s_client() -> "k8s_client_module.CoreV1Api":
    """Session-scope CoreV1Api client.

    Only meaningful inside tests gated by
    ``pytest.mark.skipif(SANDBOX_BACKEND != KUBERNETES, ...)``. The fixture
    itself does not enforce that gate — module-level ``pytestmark`` does.
    """
    from kubernetes import client as k8s_client_module

    _load_kube_config()
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
def pool_session(
    _pool_pod: _PoolPod,
) -> tuple[UUID, UUID, str]:
    """Fresh session on the module pool pod — drop-in for ``live_pod``.

    Same return shape as ``live_pod`` (``sandbox_id, session_id,
    pod_name``) but reuses the module-scoped pool pod instead of
    provisioning + tearing down a fresh one per test. Saves ~14s of pod
    startup per test.

    Per call: wipes mutable trees on the pool pod
    (``/workspace/managed/skills``, ``/workspace/managed/user_library``,
    ``/workspace/sessions``) via :func:`_cleanup_pool_workspace`, then
    sets up a fresh session workspace with a new ``session_id``. The
    returned ``sandbox_id`` is the pool pod's stable ID.

    Use this for any test that needs a sandbox pod + a session and does
    NOT terminate / restart / re-provision the pod itself. Tests that
    assert on pod lifecycle (terminate cleanup, restart count, IRSA
    env, RO mount) must keep using ``live_pod`` so they don't break
    state for subsequent tests in the module.
    """
    _cleanup_pool_workspace(_pool_pod.k8s_client, _pool_pod.pod_name)
    session_id = uuid4()
    _pool_pod.manager.setup_session_workspace(
        sandbox_id=_pool_pod.sandbox_id,
        session_id=session_id,
        llm_config=default_llm_config(
            api_key=os.environ.get("OPENAI_API_KEY", "test-key"),
        ),
        nextjs_port=None,
        skills_section="No skills available.",
    )
    return _pool_pod.sandbox_id, session_id, _pool_pod.pod_name


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

    Prefer ``pool_session`` for tests that just need a sandbox + session
    and don't mutate pod-level state; this fixture exists for tests that
    require their own pod (lifecycle assertions, terminate, etc.).
    """
    sandbox_id = uuid4()
    session_id = uuid4()
    llm_config = default_llm_config(
        api_key=os.environ.get("OPENAI_API_KEY", "test-key"),
    )

    info = _provision_with_retry(
        k8s_manager,
        sandbox_id=sandbox_id,
        user_id=_K8S_TEST_USER_ID,
        tenant_id=TEST_TENANT_ID,
        llm_config=llm_config,
    )
    assert info.status == SandboxStatus.RUNNING

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
