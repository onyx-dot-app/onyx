from __future__ import annotations

import os
import time
from collections.abc import Callable
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from kubernetes import client as k8s_client_module

    from tests.integration.common_utils.test_models import DATestUser

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import SandboxStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.db.user_library import delete_user_file
from onyx.server.features.build.db.user_library import list_user_files
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

_K8S_CRAFT_PATHS = (
    "backend/tests/integration/tests/craft/k8s/",
    "tests/integration/tests/craft/k8s/",
)


def _is_k8s_craft_request(request: pytest.FixtureRequest) -> bool:
    path = str(request.node.path).replace("\\", "/")
    return any(prefix in path for prefix in _K8S_CRAFT_PATHS)


def _sandbox_push_private_key() -> str:
    configured = os.environ.get("ONYX_SANDBOX_PUSH_PRIVATE_KEY")
    if configured:
        return configured

    raise RuntimeError(
        "ONYX_SANDBOX_PUSH_PRIVATE_KEY must be set and match the deployed "
        "api_server key for Craft K8s integration tests"
    )


@pytest.fixture(scope="module", autouse=True)
def _sandbox_push_key(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    # sidecar_client imports the config as a module constant; patch both env and modules.
    if not _is_k8s_craft_request(request):
        yield
        return

    from onyx.server.features.build import configs as build_configs
    from onyx.server.features.build.sandbox.kubernetes import sidecar_client

    push_key = _sandbox_push_private_key()
    mp = pytest.MonkeyPatch()
    mp.setenv("ONYX_SANDBOX_PUSH_PRIVATE_KEY", push_key)
    mp.setattr(build_configs, "SANDBOX_PUSH_PRIVATE_KEY", push_key)
    mp.setattr(sidecar_client, "SANDBOX_PUSH_PRIVATE_KEY", push_key)
    mp.setattr(sidecar_client, "_push_private_key", None)
    mp.setattr(sidecar_client, "_push_public_key_b64", None)
    try:
        yield
    finally:
        mp.undo()


@dataclass(frozen=True)
class SandboxHandle:
    manager: KubernetesSandboxManager
    sandbox_id: UUID
    session_id: UUID | None
    _api_user: "DATestUser | None" = None

    @property
    def api_user(self) -> "DATestUser":
        if self._api_user is None:
            raise RuntimeError("SandboxHandle has no API user bound")
        return self._api_user


def _create_api_user_and_session() -> tuple["DATestUser", UUID, UUID]:
    from tests.integration.common_utils.managers.build_session import (
        BuildSessionManager,
    )
    from tests.integration.common_utils.managers.user import UserManager

    api_user = UserManager.create(name=f"craft-k8s-{uuid4().hex[:8]}")
    session = BuildSessionManager.create(api_user, headless=True)
    sandbox = session["sandbox"]
    assert sandbox is not None, f"Session response missing sandbox: {session!r}"
    assert sandbox["status"].upper() == SandboxStatus.RUNNING.value.upper()
    return api_user, UUID(sandbox["id"]), UUID(session["id"])


def _create_api_session_for_user(api_user: "DATestUser") -> tuple[UUID, UUID]:
    from tests.integration.common_utils.managers.build_session import (
        BuildSessionManager,
    )

    session = BuildSessionManager.create(api_user, headless=True)
    sandbox = session["sandbox"]
    assert sandbox is not None, f"Session response missing sandbox: {session!r}"
    assert sandbox["status"].upper() == SandboxStatus.RUNNING.value.upper()
    return UUID(sandbox["id"]), UUID(session["id"])


def cleanup_api_user_sandbox_rows(user_id: UUID) -> None:
    try:
        with get_session_with_current_tenant() as session:
            for doc in list_user_files(session, user_id):
                delete_user_file(session, doc)
            for row in (
                session.query(ConnectorCredentialPair)
                .filter(ConnectorCredentialPair.creator_id == user_id)
                .all()
            ):
                session.delete(row)
            for row in (
                session.query(Credential).filter(Credential.user_id == user_id).all()
            ):
                session.delete(row)
            for row in session.query(Sandbox).filter(Sandbox.user_id == user_id).all():
                session.delete(row)
            for row in (
                session.query(User__UserGroup)
                .filter(User__UserGroup.user_id == user_id)
                .all()
            ):
                session.delete(row)
            user_row = session.get(User, user_id)
            if user_row is not None:
                session.delete(user_row)
            session.commit()
    except Exception:
        logger.warning(
            "Failed to clean up Craft API test user %s", user_id, exc_info=True
        )


def _terminate_and_wait(
    manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
    sandbox_id: UUID,
) -> None:
    pod_name = manager._get_pod_name(sandbox_id)
    manager.terminate(sandbox_id)
    wait_for_pod_deletion(k8s_client, pod_name, SANDBOX_NAMESPACE)


@contextmanager
def _provisioned_sandbox(
    manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[tuple["DATestUser", UUID, UUID, str], None, None]:
    """Provision through the API so proxy identity lookup can resolve the pod."""
    api_user, sandbox_id, session_id = _create_api_user_and_session()
    user_id = UUID(api_user.id)
    cleanup_rows = False
    try:
        pod_name = manager._get_pod_name(str(sandbox_id))
        try:
            yield api_user, sandbox_id, session_id, pod_name
        finally:
            _terminate_and_wait(manager, k8s_client, sandbox_id)
            cleanup_rows = True
    finally:
        if cleanup_rows:
            cleanup_api_user_sandbox_rows(user_id)


@dataclass(frozen=True)
class _PoolPod:
    api_user: "DATestUser"
    sandbox_id: UUID
    pod_name: str
    manager: KubernetesSandboxManager
    k8s_client: "k8s_client_module.CoreV1Api"


def _cleanup_pool_workspace(
    k8s_client: "k8s_client_module.CoreV1Api",
    pod_name: str,
) -> None:
    # managed/ is RO in the sandbox container; clean via sidecar.
    pod_exec(
        k8s_client,
        pod_name,
        SANDBOX_NAMESPACE,
        "find /workspace/managed/skills /workspace/managed/user_library "
        "-mindepth 1 -delete 2>/dev/null; true",
        container="sidecar",
    )
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
    from onyx.server.features.build.configs import SANDBOX_BACKEND
    from onyx.server.features.build.configs import SandboxBackend

    if SANDBOX_BACKEND != SandboxBackend.KUBERNETES:
        pytest.skip(
            "_pool_pod requires SANDBOX_BACKEND=kubernetes "
            "(run via pr-craft-k8s-tests.yml or against a local kind cluster)"
        )

    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    manager = KubernetesSandboxManager()

    try:
        with _provisioned_sandbox(manager, k8s_client) as (
            api_user,
            pool_sandbox_id,
            _initial_session_id,
            pod_name,
        ):
            yield _PoolPod(
                api_user=api_user,
                sandbox_id=pool_sandbox_id,
                pod_name=pod_name,
                manager=manager,
                k8s_client=k8s_client,
            )
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def running_sandbox(
    request: pytest.FixtureRequest,
) -> Callable[..., SandboxHandle]:
    """Return a clean handle for the module-scoped pool pod."""
    from onyx.server.features.build.configs import SANDBOX_BACKEND
    from onyx.server.features.build.configs import SandboxBackend

    if SANDBOX_BACKEND != SandboxBackend.KUBERNETES:
        pytest.skip(
            "running_sandbox fixture requires SANDBOX_BACKEND=kubernetes "
            "(run via pr-craft-k8s-tests.yml or against a local kind cluster)"
        )
    pool: _PoolPod = request.getfixturevalue("_pool_pod")

    _cleanup_pool_workspace(pool.k8s_client, pool.pod_name)

    extra_sandbox_user_ids: dict[UUID, UUID] = {}

    def _register_extra(sandbox_id: UUID, api_user: "DATestUser") -> None:
        extra_sandbox_user_ids[sandbox_id] = UUID(api_user.id)

    def _make(
        with_session: bool = False,
    ) -> SandboxHandle:
        session_id: UUID | None = None
        sandbox_id = pool.sandbox_id
        api_user: "DATestUser | None" = pool.api_user
        if with_session:
            sandbox_id, session_id = _create_api_session_for_user(pool.api_user)
            if sandbox_id != pool.sandbox_id:
                _register_extra(sandbox_id, pool.api_user)

        def _cleanup() -> None:
            errors: list[BaseException] = []
            for extra_id, user_id in extra_sandbox_user_ids.items():
                try:
                    _terminate_and_wait(pool.manager, pool.k8s_client, extra_id)
                except Exception as exc:
                    errors.append(exc)
                    continue
                cleanup_api_user_sandbox_rows(user_id)
            if errors:
                raise RuntimeError(
                    f"Failed to clean up {len(errors)} extra sandbox pod(s)"
                ) from errors[0]

        request.addfinalizer(_cleanup)

        return SandboxHandle(
            manager=pool.manager,
            sandbox_id=sandbox_id,
            session_id=session_id,
            _api_user=api_user,
        )

    return _make


@pytest.fixture(scope="session")
def k8s_client() -> "k8s_client_module.CoreV1Api":
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
    """Run a one-shot ``/bin/sh -c`` command in a pod container; return combined output.

    Pass ``container="sidecar"`` to write to ``/workspace/managed/`` (RO in the
    sandbox container).
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


def wait_for_pod_deletion(
    client: "k8s_client_module.CoreV1Api",
    pod_name: str,
    namespace: str = SANDBOX_NAMESPACE,
    max_attempts: int = 30,
) -> None:
    """Wait until the pod is fully gone (read returns 404)."""
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


def wait_until_healthy(
    manager: KubernetesSandboxManager,
    sandbox_id: UUID,
    max_attempts: int = 15,
    timeout: float = 5.0,
) -> None:
    """Poll ``health_check`` until it passes; the sidecar probe can lag from the
    out-of-cluster runner, so a single-shot check is flaky."""
    for _ in range(max_attempts):
        if manager.health_check(sandbox_id, timeout=timeout):
            return
        time.sleep(2)
    raise RuntimeError(f"Sandbox {sandbox_id} never became healthy")


@pytest.fixture(scope="function")
def k8s_manager() -> Generator[KubernetesSandboxManager, None, None]:
    """Initialise DB engine + tenant context and return the K8s manager."""
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield KubernetesSandboxManager()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def pool_session(
    _pool_pod: _PoolPod,
) -> tuple[UUID, UUID, str]:
    _cleanup_pool_workspace(_pool_pod.k8s_client, _pool_pod.pod_name)
    sandbox_id, session_id = _create_api_session_for_user(_pool_pod.api_user)
    if sandbox_id != _pool_pod.sandbox_id:
        _terminate_and_wait(_pool_pod.manager, _pool_pod.k8s_client, sandbox_id)
        pytest.fail(
            f"pool_session: API returned a new sandbox {sandbox_id!r} instead "
            f"of the pool pod {_pool_pod.sandbox_id!r}; the pool pod may have "
            "been terminated externally."
        )
    return sandbox_id, session_id, _pool_pod.pod_name


@pytest.fixture(scope="function")
def live_pod(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[tuple[UUID, UUID, str], None, None]:
    with _provisioned_sandbox(k8s_manager, k8s_client) as (
        _api_user,
        sandbox_id,
        session_id,
        pod_name,
    ):
        yield sandbox_id, session_id, pod_name


@pytest.fixture(scope="function")
def pool_api_user(_pool_pod: _PoolPod) -> "DATestUser":
    return _pool_pod.api_user


@pytest.fixture(scope="function")
def provisioned_sandbox(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[tuple[UUID, str], None, None]:
    with _provisioned_sandbox(k8s_manager, k8s_client) as (
        _api_user,
        sandbox_id,
        _session_id,
        pod_name,
    ):
        yield sandbox_id, pod_name
