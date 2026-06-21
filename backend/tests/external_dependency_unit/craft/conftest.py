"""Fixtures for build mode tests.

See ``docs/craft/test-master-plan.md`` Part V for the contract these fixtures
honour and the broader test layer model.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import threading
import time
import zipfile
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from collections.abc import Sequence
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
from sqlalchemy import text
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import AccountType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.llm import fetch_default_llm_model
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
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
from onyx.llm.constants import LlmProviderNames
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import default_llm_config
from tests.external_dependency_unit.craft.stubs import StubSandboxManager

_DEV_PUSH_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


@pytest.fixture(scope="module", autouse=True)
def _sandbox_push_key() -> Generator[None, None, None]:
    # Module-scoped so it's set before ``_pool_pod`` (also module-scoped)
    # provisions its pod. ``sidecar_client`` imports the config value as a
    # module constant, so patch both the process env and the already-imported
    # modules.
    from onyx.server.features.build import configs as build_configs
    from onyx.server.features.build.sandbox.kubernetes import sidecar_client

    mp = pytest.MonkeyPatch()
    mp.setenv("ONYX_SANDBOX_PUSH_PRIVATE_KEY", _DEV_PUSH_KEY)
    mp.setattr(build_configs, "SANDBOX_PUSH_PRIVATE_KEY", _DEV_PUSH_KEY)
    mp.setattr(sidecar_client, "SANDBOX_PUSH_PRIVATE_KEY", _DEV_PUSH_KEY)
    mp.setattr(sidecar_client, "_push_private_key", None)
    mp.setattr(sidecar_client, "_push_public_key_b64", None)
    try:
        yield
    finally:
        mp.undo()


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
    return [col.key for col in class_mapper(model).primary_key]  # ty: ignore[invalid-return-type]


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


def _best_effort_delete(model: type[Any], ids: Iterable[Any]) -> None:
    """Delete rows by id on a fresh tenant session, swallowing errors.

    For fixture teardown: a failed delete (e.g. an FK that doesn't cascade)
    must not fail the test — at worst the row leaks, as it did before.
    """
    ids = [i for i in ids if i is not None]
    if not ids:
        return
    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
        try:
            with get_session_with_current_tenant() as session:
                # Fail fast instead of hanging if another (uncommitted) test
                # session still holds locks on these rows.
                session.execute(text("SET lock_timeout = '10s'"))
                for row_id in ids:
                    row = session.get(model, row_id)
                    if row is not None:
                        session.delete(row)
                session.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    except Exception:
        pass


def _best_effort_delete_memberships(group_ids: list[int]) -> None:
    """Delete User__UserGroup rows for the given groups (composite PK, so not
    deletable by ``_best_effort_delete``). Best-effort."""
    if not group_ids:
        return
    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
        try:
            with get_session_with_current_tenant() as session:
                session.execute(text("SET lock_timeout = '10s'"))
                session.query(User__UserGroup).filter(
                    User__UserGroup.user_group_id.in_(group_ids)
                ).delete(synchronize_session=False)
                session.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    except Exception:
        pass


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


@pytest.fixture(scope="module", autouse=True)
def _seed_default_llm_provider() -> Generator[None, None, None]:
    """Seed a default LLM provider so the real provisioning path resolves one.

    No-op (and no teardown) if the DB already has a default. The fake key is
    never invoked — tests forward the resolved config to ``provision()`` only.
    """
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    seeded_name: str | None = None
    try:
        with get_session_with_current_tenant() as session:
            if fetch_default_llm_model(session) is None:
                seeded_name = f"craft-ci-default-{uuid4().hex[:8]}"
                provider = upsert_llm_provider(
                    LLMProviderUpsertRequest(
                        name=seeded_name,
                        provider=LlmProviderNames.OPENAI,
                        api_key="sk-craft-ci-not-used",
                        api_key_changed=True,
                        model_configurations=[
                            ModelConfigurationUpsertRequest(
                                name="gpt-5-mini", is_visible=True
                            )
                        ],
                    ),
                    db_session=session,
                )
                update_default_provider(
                    provider_id=provider.id,
                    model_name="gpt-5-mini",
                    db_session=session,
                )
                session.commit()
        yield
    finally:
        if seeded_name is not None:
            with get_session_with_current_tenant() as session:
                existing = fetch_existing_llm_provider(
                    name=seeded_name, db_session=session
                )
                if existing is not None:
                    remove_llm_provider(session, existing.id)
                    session.commit()
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


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
def test_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[User, None, None]:
    """A committed test user; deleted on teardown (cascades its sandboxes,
    sessions, and memberships)."""
    password_helper = PasswordHelper()
    user = User(
        id=uuid4(),
        email=f"build_test_{uuid4().hex[:8]}@example.com",
        hashed_password=password_helper.hash(password_helper.generate()),
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.EXT_PERM_USER,
        account_type=AccountType.EXT_PERM_USER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    yield user
    # Release any uncommitted locks the test left on this session (e.g. an
    # ensure_sandbox_pat flush without commit) before the separate-session
    # delete below — otherwise its DELETE deadlocks on rows that cascade from
    # this user, since db_session (the lock holder) only tears down later (LIFO).
    db_session.rollback()
    _best_effort_delete(User, [user.id])


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
        # create_sandbox__no_commit starts at PROVISIONING; move to the asked status.
        row = create_sandbox__no_commit(db_session=db_session, user_id=owner.id)
        if status != SandboxStatus.PROVISIONING:
            update_sandbox_status__no_commit(db_session, row.id, status)
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
    _k8s_client: "k8s_client_module.CoreV1Api"
    # Required to provision additional sandboxes for other users.
    _db_session: Session
    _register_extra: Callable[[UUID], None]

    @property
    def workspace_path(self) -> WorkspaceProxy:
        return WorkspaceProxy(
            _k8s_client=self._k8s_client,
            _pod_name=self.manager._get_pod_name(self.sandbox_id),
            _sandbox_id=self.sandbox_id,
        )

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
        sandbox_id = _provision_sandbox_via_app(user.id)
        self._register_extra(sandbox_id)

        # Committed on another session; refresh before reading.
        self._db_session.expire_all()
        sandbox_row = self._db_session.get(Sandbox, sandbox_id)
        assert sandbox_row is not None

        if status != SandboxStatus.RUNNING:
            sandbox_row.status = status
            self._db_session.commit()

        workspace = WorkspaceProxy(
            _k8s_client=self._k8s_client,
            _pod_name=self.manager._get_pod_name(sandbox_id),
            _sandbox_id=sandbox_id,
        )
        return sandbox_row, workspace

    def provision_for_many(
        self,
        users: Sequence[User],
        status: SandboxStatus = SandboxStatus.RUNNING,
    ) -> list[tuple[Sandbox, WorkspaceProxy]]:
        """Parallel ``provision_for``; preserves input order.

        ContextVars don't propagate to ThreadPoolExecutor workers, so each
        worker re-pins the tenant id before touching the DB. Each
        successfully-provisioned pod is registered for teardown
        immediately so a partial failure still cleans up.
        """
        if not users:
            return []

        tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()

        def _worker(user: User) -> UUID:
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            try:
                return _provision_sandbox_via_app(user.id)
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        sandbox_ids: dict[User, UUID] = {}
        worker_error: Exception | None = None
        with ThreadPoolExecutor(max_workers=min(len(users), 8)) as pool:
            futures = {pool.submit(_worker, user): user for user in users}
            for fut in as_completed(futures):
                user = futures[fut]
                try:
                    sandbox_id = fut.result()
                except Exception as e:
                    if worker_error is None:
                        worker_error = e
                    continue
                sandbox_ids[user] = sandbox_id
                self._register_extra(sandbox_id)

        # Apply the requested status to every pod that came up — including
        # on partial failure — so teardown sees consistent DB state before
        # the error propagates.
        self._db_session.expire_all()
        if status != SandboxStatus.RUNNING and sandbox_ids:
            for sandbox_id in sandbox_ids.values():
                row = self._db_session.get(Sandbox, sandbox_id)
                assert row is not None
                row.status = status
            self._db_session.commit()

        if worker_error is not None:
            raise worker_error

        results: list[tuple[Sandbox, WorkspaceProxy]] = []
        for user in users:
            sandbox_id = sandbox_ids[user]
            sandbox_row = self._db_session.get(Sandbox, sandbox_id)
            assert sandbox_row is not None

            workspace = WorkspaceProxy(
                _k8s_client=self._k8s_client,
                _pod_name=self.manager._get_pod_name(sandbox_id),
                _sandbox_id=sandbox_id,
            )
            results.append((sandbox_row, workspace))

        return results


def _create_committed_craft_user() -> UUID:
    """Commit a standard craft user and return its id."""
    password_helper = PasswordHelper()
    user_id = uuid4()
    with get_session_with_current_tenant() as session:
        session.add(
            User(
                id=user_id,
                email=f"craft_sandbox_{user_id.hex[:8]}@example.com",
                hashed_password=password_helper.hash(password_helper.generate()),
                is_active=True,
                is_superuser=False,
                is_verified=True,
                role=UserRole.BASIC,
                account_type=AccountType.STANDARD,
            )
        )
        session.commit()
    return user_id


def _provision_sandbox_via_app(user_id: UUID) -> UUID:
    """Provision via the app's own ``ensure_sandbox_running`` (creates the row
    + provisions the pod), so test setup can't drift from prod. One-shot retry
    absorbs kind scheduling flake.
    """
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            with get_session_with_current_tenant() as session:
                sandbox = SessionManager(session).ensure_sandbox_running(user_id)
                sandbox_id = sandbox.id
                session.commit()
                return sandbox_id
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == 0:
                continue
            raise
    raise RuntimeError(
        f"ensure_sandbox_running exhausted retries for user {user_id}: {last_err}"
    ) from last_err


@contextmanager
def _provisioned_sandbox(
    manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[tuple[UUID, str], None, None]:
    """The one way to get a real provisioned sandbox in a test.

    The proxy resolves pod identity via the DB (pod IP -> Sandbox.user_id), so
    a pod without a committed Sandbox row fails closed — gated egress 403s and
    snapshot uploads are silently dropped. Provisioning through the app path
    guarantees the row exists. Yields ``(sandbox_id, pod_name)``; tears the pod
    + rows down on exit.
    """
    user_id = _create_committed_craft_user()
    try:
        sandbox_id = _provision_sandbox_via_app(user_id)
        pod_name = manager._get_pod_name(str(sandbox_id))
        try:
            yield sandbox_id, pod_name
        finally:
            try:
                manager.terminate(sandbox_id)
            except Exception:
                pass
            try:
                wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)
            except Exception:
                pass
    finally:
        with get_session_with_current_tenant() as session:
            for row in session.query(Sandbox).filter(Sandbox.user_id == user_id).all():
                session.delete(row)
            user_row = session.get(User, user_id)
            if user_row is not None:
                session.delete(user_row)
            session.commit()


def _setup_default_session(
    manager: KubernetesSandboxManager,
    sandbox_id: UUID,
    session_id: UUID,
    llm_config: LLMProviderConfig | None = None,
) -> None:
    """Set up a session workspace with the standard test defaults."""
    manager.setup_session_workspace(
        sandbox_id=sandbox_id,
        session_id=session_id,
        llm_config=llm_config
        or default_llm_config(api_key=os.environ.get("OPENAI_API_KEY", "test-key")),
        nextjs_port=None,
        skills_section="No skills available.",
    )


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


def _cleanup_pool_workspace(
    k8s_client: "k8s_client_module.CoreV1Api",
    pod_name: str,
) -> None:
    """Wipe mutable trees on the pool pod before the next test runs.

    ``managed/`` is read-only in the sandbox app container but writable from
    the native init sidecar, so we exec via the sidecar for the skills +
    user_library subtrees. ``sessions/`` is on a shared emptyDir, writable from
    either container.
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

    The pool sandbox's pod identity is fixed regardless of any ``user=``
    passed to ``running_sandbox()``; for a user-owned pod use
    ``SandboxHandle.provision_for(user)``.
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

    try:
        with _provisioned_sandbox(manager, k8s_client) as (pool_sandbox_id, pod_name):
            yield _PoolPod(
                sandbox_id=pool_sandbox_id,
                pod_name=pod_name,
                manager=manager,
                k8s_client=k8s_client,
            )
    finally:
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

    The ``user=`` kwarg sets the owner of the session row (when
    ``with_session=True``) but does not change the pool pod's identity. For a
    user-owned *pod*, call ``SandboxHandle.provision_for(user)`` instead.
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

            _setup_default_session(pool.manager, pool.sandbox_id, session_id, config)

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
            _k8s_client=pool.k8s_client,
            _db_session=db_session,
            _register_extra=_register_extra,
        )

    return _make


@pytest.fixture(scope="function")
def granted_users(
    db_session: Session,
    request: pytest.FixtureRequest,
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
    created_user_ids: list[UUID] = []
    created_group_ids: list[int] = []

    # Delete users (cascades their sandboxes / sessions / memberships), then
    # any membership left by a pre-existing user (its user_group_id FK is
    # RESTRICT, so it would block the group delete), then the groups we made.
    # Best-effort so teardown can't fail a test.
    def _cleanup() -> None:
        _best_effort_delete(User, created_user_ids)
        _best_effort_delete_memberships(created_group_ids)
        _best_effort_delete(UserGroup, created_group_ids)

    request.addfinalizer(_cleanup)

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
                created_group_ids.append(group.id)

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
                    created_user_ids.append(user.id)

                # One RUNNING sandbox per user.
                sandbox_row = create_sandbox__no_commit(
                    db_session=db_session, user_id=user.id
                )
                update_sandbox_status__no_commit(
                    db_session, sandbox_row.id, SandboxStatus.RUNNING
                )

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
    request: pytest.FixtureRequest,
    tenant_context: None,  # noqa: ARG001
) -> Callable[..., Skill]:
    """Factory: create a ``Skill`` row + its bundle in the file store.

    Convenience wrapper over the admin-skills create path. Tests that exercise
    the HTTP boundary should still go through the admin API; this factory is
    for tests that need a Skill row to be **present** without making HTTP
    calls. The Skill row is reclaimed by ``_isolate_skill_tables``; the bundle
    blob is deleted on teardown here.
    """
    file_store = get_default_file_store()
    file_store.initialize()
    bundle_file_ids: list[str] = []

    def _cleanup() -> None:
        for file_id in bundle_file_ids:
            try:
                file_store.delete_file(file_id, error_on_missing=False)
            except Exception:
                pass

    request.addfinalizer(_cleanup)

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
        bundle_file_ids.append(bundle_file_id)

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
    construction time) AND ``sandbox.factory._sandbox_manager_instance`` so any
    deferred lookup also lands on the stub. The LLM lookup runs for real
    against the provider from ``_seed_default_llm_provider``.
    """
    monkeypatch.setattr(
        "onyx.server.features.build.session.manager.get_sandbox_manager",
        lambda: stub_sandbox_manager,
    )
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.factory._sandbox_manager_instance",
        stub_sandbox_manager,
    )
    sm = SessionManager(db_session)
    # Sanity: SessionManager captured the stub at construction.
    assert sm._sandbox_manager is stub_sandbox_manager
    return sm


def assert_lock_serializes_two_threads(
    redis_client: Redis | TenantRedisClient,  # type: ignore[type-arg]
    lock_key: str,
) -> None:
    """Verify two concurrent acquirers contend on ``lock_key`` — one waits.

    Spawns two threads that race for the same Redis lock; the first
    thread acquires + holds, the second observes that a non-blocking
    acquire fails (the serialization point). Cleans the key before and
    after.
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
    command: str,
    container: str = "sandbox",
) -> str:
    """Run a one-shot command in a pod container; return combined output.

    Defaults to the ``sandbox`` container. Pass ``container="sidecar"`` for
    operations that need to write to ``/workspace/managed/`` (read-only in
    the sandbox container) or inspect the sidecar's environment.

    ``command`` is a shell-string run via ``/bin/sh -c``.
    """
    from kubernetes.stream import stream as k8s_stream

    argv = ["/bin/sh", "-c", command]
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


def pod_exec_async(
    client: "k8s_client_module.CoreV1Api",
    pod_name: str,
    namespace: str,
    url: str,
    output_path: str,
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    body_file: str | None = None,
    max_time_s: int = 240,
    container: str = "sandbox",
    proxy_session_id: str | None = None,
) -> None:
    """Kick off a background sandbox-side ``curl``, writing ``{status}\\n{body}``
    to a tempfile only after curl exits. Returns immediately; poll via
    ``wait_for_pod_exec_output`` (a valid leading integer means done).

    ``proxy_session_id`` mimics the ``session-proxy-tag`` opencode plugin,
    tagging the request with the session id as ``Proxy-Authorization`` userinfo
    so the proxy can resolve the session. Omit it to exercise the untagged,
    fail-closed gate path.

    ``body_file`` (mutually exclusive with ``body``) sends the body from an
    in-pod path via ``--data-binary @path``; use this for payloads big enough to
    trip the apiserver's exec URL size limit (e.g. > 1 MiB).
    """
    if body is not None and body_file is not None:
        raise ValueError("pass either body or body_file, not both")
    header_args = ""
    for key, value in (headers or {}).items():
        header_args += f" -H {json.dumps(f'{key}: {value}')}"
    if body is not None:
        body_arg = f" --data {json.dumps(body)}"
    elif body_file is not None:
        body_arg = f" --data-binary @{body_file}"
    else:
        body_arg = ""
    # Override the ambient proxy with the session id as basic-auth userinfo.
    proxy_arg = (
        f" -x {json.dumps(f'http://{proxy_session_id}@sandbox-proxy:8080')}"
        if proxy_session_id is not None
        else ""
    )
    script = (
        f"nohup sh -c '"
        f"curl -s -X {method}{header_args}{body_arg}{proxy_arg} "
        f"--max-time {max_time_s} "
        f'-o {output_path}.body -w "%{{http_code}}" {json.dumps(url)} '
        f"> {output_path}.code 2>&1; "
        f'{{ cat {output_path}.code; printf "\\n"; cat {output_path}.body; }} '
        f"> {output_path}"
        f"' > /dev/null 2>&1 &"
    )
    pod_exec(client, pod_name, namespace, script, container=container)


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


def wait_for_pod_exec_output(
    client: "k8s_client_module.CoreV1Api",
    pod_name: str,
    output_path: str,
    timeout_s: float,
    namespace: str = SANDBOX_NAMESPACE,
    container: str = "sandbox",
) -> tuple[int, str]:
    """Poll the ``pod_exec_async`` tempfile until it appears, returning
    ``(status_code, body)`` parsed from its ``{status}\\n{body}`` layout.
    Raises on timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        raw = pod_exec(
            client,
            pod_name,
            namespace,
            f"cat {output_path} 2>/dev/null || true",
            container=container,
        )
        if raw:
            head, _, rest = raw.partition("\n")
            head = head.strip()
            if head.isdigit():
                return int(head), rest
        time.sleep(2)
    raise RuntimeError(
        f"pod_exec output {output_path} on pod {pod_name} did not arrive within "
        f"{timeout_s:.1f}s"
    )


def wait_for_proxy_redeploy(
    client: "k8s_client_module.CoreV1Api",
    timeout_s: float = 120,
) -> None:
    """Wait until the sandbox-proxy Deployment reports a ready replica.

    Used after a proxy-pod respawn so the next test doesn't hit a half-baked
    Deployment. Polls both Deployment status and pod-level readiness.
    """
    from kubernetes import client as k8s_client_module

    from onyx.server.features.build.configs import SANDBOX_PROXY_NAMESPACE

    proxy_component_label = "app.kubernetes.io/component=sandbox-proxy"
    apps_v1 = k8s_client_module.AppsV1Api()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        deployments = apps_v1.list_namespaced_deployment(
            namespace=SANDBOX_PROXY_NAMESPACE,
            label_selector=proxy_component_label,
        )
        for deploy in deployments.items or []:
            ready = deploy.status.ready_replicas or 0
            desired = (
                deploy.spec.replicas if deploy.spec and deploy.spec.replicas else 1
            )
            if ready >= desired:
                pods = client.list_namespaced_pod(
                    namespace=SANDBOX_PROXY_NAMESPACE,
                    label_selector=proxy_component_label,
                )
                ready_pods = [
                    p
                    for p in (pods.items or [])
                    if any(cs.ready for cs in (p.status.container_statuses or []))
                ]
                if ready_pods:
                    return
        time.sleep(2)
    raise RuntimeError(
        f"sandbox-proxy Deployment did not return to ready within {timeout_s:.1f}s"
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
# The cluster check happens implicitly when ``k8s_client`` or the manager makes
# its first API call.
# ---------------------------------------------------------------------------


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
    _setup_default_session(_pool_pod.manager, _pool_pod.sandbox_id, session_id)
    return _pool_pod.sandbox_id, session_id, _pool_pod.pod_name


@pytest.fixture(scope="function")
def live_pod(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[tuple[UUID, UUID, str], None, None]:
    """Provision a fresh sandbox + session pod, torn down on exit.

    Yields ``(sandbox_id, session_id, pod_name)``. Prefer ``pool_session``
    unless the test mutates pod-level state (lifecycle assertions, terminate).
    """
    with _provisioned_sandbox(k8s_manager, k8s_client) as (sandbox_id, pod_name):
        session_id = uuid4()
        _setup_default_session(k8s_manager, sandbox_id, session_id)
        yield sandbox_id, session_id, pod_name


@pytest.fixture(scope="function")
def provisioned_sandbox(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[tuple[UUID, str], None, None]:
    """A provisioned sandbox (committed rows + pod), without a session.

    For tests that need a real egressing pod as a precondition but not a
    session workspace (e.g. the egress proxy test). Backed by the same
    ``_provisioned_sandbox`` primitive, so the sandbox is identity-resolvable
    by the proxy. Yields ``(sandbox_id, pod_name)``.
    """
    with _provisioned_sandbox(k8s_manager, k8s_client) as (sandbox_id, pod_name):
        yield sandbox_id, pod_name
