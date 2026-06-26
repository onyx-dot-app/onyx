"""Shared Kubernetes fixtures and helpers for Craft integration tests."""

from __future__ import annotations

import json
import os
import shlex
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Sequence
from contextlib import contextmanager
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field
from pathlib import PurePosixPath
from typing import NamedTuple
from typing import TYPE_CHECKING
from uuid import UUID
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from kubernetes import client as k8s_client_module

    from tests.integration.common_utils.test_models import DATestUser

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_PROXY_PORT
from onyx.server.features.build.db.user_library import delete_user_file
from onyx.server.features.build.db.user_library import list_user_files
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager

logger = setup_logger()

# Sandboxes this suite provisions, so the autouse reaper only terminates our own
# leaks and never touches unrelated sandboxes on a shared/local cluster.
_SUITE_SANDBOX_IDS: set[UUID] = set()


def suite_sandbox_ids() -> set[UUID]:
    """Snapshot of sandbox IDs created by this suite (for the leaked-pod reaper)."""
    return set(_SUITE_SANDBOX_IDS)


class PoolSession(NamedTuple):
    """Returned by ``pool_session`` and ``live_pod`` fixtures."""

    sandbox_id: UUID
    session_id: UUID
    pod_name: str


class OwnedLivePod(NamedTuple):
    """Returned by ``owned_live_pod`` and ``_provisioned_sandbox``."""

    api_user: "DATestUser"
    sandbox_id: UUID
    session_id: UUID
    pod_name: str


class PodExecResult(NamedTuple):
    """Returned by ``wait_for_pod_exec_output``."""

    status_code: int
    body: str


_K8S_CRAFT_PATHS = (
    "backend/tests/integration/tests/craft/k8s/",
    "tests/integration/tests/craft/k8s/",
)


def _is_k8s_craft_request(request: pytest.FixtureRequest) -> bool:
    path = str(request.node.path).replace("\\", "/")
    return any(prefix in path for prefix in _K8S_CRAFT_PATHS)


def _sandbox_push_private_key() -> str:
    configured = os.environ.get("ONYX_SANDBOX_PUSH_PRIVATE_KEY")
    if not configured:
        pytest.fail(
            "ONYX_SANDBOX_PUSH_PRIVATE_KEY must be set for the k8s Craft suite. "
            "API-provisioned pods verify pushes against the deployed server's key, "
            "so a generated fallback would silently mismatch (false-pass negative "
            "skip tests, hard-fail positive push tests). CI provides this from the "
            "deployed server's config."
        )
    return configured


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
class WorkspaceProxy:
    """``pathlib.Path``-shaped proxy for a sandbox pod's ``/workspace`` root."""

    _k8s_client: "k8s_client_module.CoreV1Api"
    _pod_name: str
    _rel_parts: tuple[str, ...] = field(default_factory=tuple)

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
        # -L too: dangling symlinks count as present.
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
        out = self._exec(
            f"readlink -f {shlex.quote(self._abs_posix)} || echo {shlex.quote(self._abs_posix)}"
        )
        resolved = out.strip()
        if resolved.startswith("/workspace/"):
            rel = resolved[len("/workspace/") :]
        else:
            rel = resolved.lstrip("/")
        parts = tuple(p for p in rel.split("/") if p)
        return WorkspaceProxy(
            _k8s_client=self._k8s_client,
            _pod_name=self._pod_name,
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
                    _rel_parts=parts,
                )
            )
        return results

    def wait_for_file(
        self,
        *,
        expected: bytes | None = None,
        timeout_s: float = 20,
    ) -> None:
        deadline = time.monotonic() + timeout_s
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                if self.exists() and (
                    expected is None or self.read_bytes() == expected
                ):
                    return
            except Exception as e:
                last_error = e
            time.sleep(0.5)
        if last_error is not None:
            raise AssertionError(f"Timed out waiting for {self}: {last_error}") from (
                last_error
            )
        raise AssertionError(f"Timed out waiting for {self}")

    def wait_for_bytes(self, expected: bytes, *, timeout_s: float = 20) -> None:
        deadline = time.monotonic() + timeout_s
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                if self.exists() and self.read_bytes().endswith(expected):
                    return
            except Exception as e:
                last_error = e
            time.sleep(0.5)
        if last_error is not None:
            raise AssertionError(f"Timed out waiting for {self}: {last_error}") from (
                last_error
            )
        raise AssertionError(f"Timed out waiting for {self}")

    def wait_for_absent(self, *, timeout_s: float = 20) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not self.exists():
                return
            time.sleep(0.5)
        raise AssertionError(f"Timed out waiting for {self} to be absent")

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
    """Handle returned by the ``running_sandbox`` factory."""

    manager: KubernetesSandboxManager
    sandbox_id: UUID
    session_id: UUID | None
    _k8s_client: "k8s_client_module.CoreV1Api"
    _register_extra: Callable[[UUID, "DATestUser"], None]
    _api_user: "DATestUser | None" = None

    @property
    def api_user(self) -> "DATestUser":
        if self._api_user is None:
            raise RuntimeError("SandboxHandle has no API user bound")
        return self._api_user

    @property
    def workspace_path(self) -> WorkspaceProxy:
        return WorkspaceProxy(
            _k8s_client=self._k8s_client,
            _pod_name=self.manager._get_pod_name(self.sandbox_id),
        )

    def provision_api_user(
        self,
        api_user: "DATestUser",
    ) -> WorkspaceProxy:
        _session_id, sandbox_id = BuildSessionManager.create_with_sandbox(api_user)
        _SUITE_SANDBOX_IDS.add(sandbox_id)
        if sandbox_id == self.sandbox_id:
            if self._api_user is not None and api_user.id != self._api_user.id:
                raise AssertionError(
                    "API returned the pool sandbox for a different user; "
                    f"pool_user={self._api_user.id} api_user={api_user.id}"
                )
        else:
            self._register_extra(sandbox_id, api_user)

        return WorkspaceProxy(
            _k8s_client=self._k8s_client,
            _pod_name=self.manager._get_pod_name(sandbox_id),
        )

    def provision_api_users(
        self,
        users: Sequence["DATestUser"],
    ) -> list[WorkspaceProxy]:
        return [self.provision_api_user(user) for user in users]


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


def _delete_sandbox_row(sandbox_id: UUID) -> None:
    """Delete a single Sandbox row, leaving its owner intact — for extra sandboxes
    provisioned against the shared pool user, whose row must survive the module."""
    try:
        with get_session_with_current_tenant() as session:
            row = session.get(Sandbox, sandbox_id)
            if row is not None:
                session.delete(row)
                session.commit()
    except Exception:
        logger.warning("Failed to delete sandbox row %s", sandbox_id, exc_info=True)


@contextmanager
def _provisioned_sandbox(
    manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[OwnedLivePod, None, None]:
    """API-provisioned sandbox with committed DB rows; tears down pod + rows on exit.

    The proxy resolves identity via the DB (pod IP -> Sandbox.user_id), so a pod
    without a committed Sandbox row fails closed.
    """
    api_user = UserManager.create(name=f"craft-k8s-{uuid4().hex[:8]}")
    session_id, sandbox_id = BuildSessionManager.create_with_sandbox(api_user)
    _SUITE_SANDBOX_IDS.add(sandbox_id)
    user_id = UUID(api_user.id)
    try:
        pod_name = manager._get_pod_name(str(sandbox_id))
        try:
            yield OwnedLivePod(
                api_user=api_user,
                sandbox_id=sandbox_id,
                session_id=session_id,
                pod_name=pod_name,
            )
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
    """Wipe mutable trees on the pool pod before the next test runs."""
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
    """Module-scoped sandbox pod shared by all ``running_sandbox()`` calls."""
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
    """Factory: hand out a ``SandboxHandle`` bound to the module pool pod.

    Wipes mutable trees on the pool pod before yielding so every test sees a
    clean slate. Extra user-owned pods come from
    ``SandboxHandle.provision_api_user``.
    """
    from onyx.server.features.build.configs import SANDBOX_BACKEND
    from onyx.server.features.build.configs import SandboxBackend

    if SANDBOX_BACKEND != SandboxBackend.KUBERNETES:
        pytest.skip(
            "running_sandbox fixture requires SANDBOX_BACKEND=kubernetes "
            "(run via pr-craft-k8s-tests.yml or against a local kind cluster)"
        )
    pool: _PoolPod = request.getfixturevalue("_pool_pod")

    _cleanup_pool_workspace(pool.k8s_client, pool.pod_name)

    # Per-test pods from provision_api_user; teardown terminates these (not the pool pod).
    extra_sandbox_user_ids: dict[UUID, UUID] = {}
    # Extra sandboxes provisioned for the *pool* user (when create_with_sandbox
    # re-provisions because the pool pod was unhealthy): drop only the row, never
    # the pool user.
    pool_extra_sandbox_ids: list[UUID] = []

    def _register_extra(sandbox_id: UUID, api_user: "DATestUser") -> None:
        extra_sandbox_user_ids[sandbox_id] = UUID(api_user.id)

    def _make(
        with_session: bool = False,
    ) -> SandboxHandle:
        session_id: UUID | None = None
        sandbox_id = pool.sandbox_id
        api_user: "DATestUser | None" = pool.api_user
        if with_session:
            session_id, sandbox_id = BuildSessionManager.create_with_sandbox(
                pool.api_user
            )
            _SUITE_SANDBOX_IDS.add(sandbox_id)
            if sandbox_id != pool.sandbox_id:
                pool_extra_sandbox_ids.append(sandbox_id)

        def _cleanup() -> None:
            def _terminate(extra_id: UUID) -> None:
                try:
                    pool.manager.terminate(extra_id)
                except Exception:
                    pass
                try:
                    wait_for_pod_deletion(
                        pool.k8s_client,
                        pool.manager._get_pod_name(extra_id),
                        SANDBOX_NAMESPACE,
                    )
                except Exception:
                    pass

            for extra_id, user_id in extra_sandbox_user_ids.items():
                _terminate(extra_id)
                cleanup_api_user_sandbox_rows(user_id)
            for extra_id in pool_extra_sandbox_ids:
                _terminate(extra_id)
                _delete_sandbox_row(extra_id)

        request.addfinalizer(_cleanup)

        return SandboxHandle(
            manager=pool.manager,
            sandbox_id=sandbox_id,
            session_id=session_id,
            _k8s_client=pool.k8s_client,
            _register_extra=_register_extra,
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
    """Kick off a background sandbox-side ``curl``; poll via ``wait_for_pod_exec_output``.

    Writes ``{status}\\n{body}`` to a tempfile only after curl exits.
    ``proxy_session_id`` tags the request as ``Proxy-Authorization`` userinfo;
    omit it for the untagged fail-closed path. ``body_file`` (exclusive with
    ``body``) sends the body from an in-pod path, for payloads that would trip
    the apiserver's exec URL size limit.
    """
    if body is not None and body_file is not None:
        raise ValueError("pass either body or body_file, not both")
    header_args = ""
    for key, value in (headers or {}).items():
        header_args += f" -H {json.dumps(f'{key}: {value}')}"
    if body is not None:
        body_arg = f" --data {json.dumps(body)}"
    elif body_file is not None:
        # Suppress Expect:100-continue so the body is read before the proxy responds;
        # otherwise the 403 carries no JSON body and the len-check path is skipped.
        body_arg = f" --data-binary @{body_file} -H {json.dumps('Expect:')}"
    else:
        body_arg = ""
    proxy_arg = (
        f" -x {json.dumps(f'http://{proxy_session_id}@sandbox-proxy:{SANDBOX_PROXY_PORT}')}"
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
) -> None:
    """Poll the pod's ``Ready`` condition via the kube-API.

    Uses a pod read (the apiserver path, reachable from the out-of-cluster
    runner), NOT ``manager.health_check`` — which does a direct HTTP GET to the
    pod IP that the runner cannot route to. The sidecar's own ``readinessProbe``
    (``/health`` on the push-daemon port) gates pod readiness, so ``Ready=True``
    already means the sidecar is healthy and the agent container is running.
    """
    pod_name = manager._get_pod_name(str(sandbox_id))
    for _ in range(max_attempts):
        pod = manager._core_api.read_namespaced_pod(
            name=pod_name, namespace=manager._namespace
        )
        conditions = pod.status.conditions or []
        if any(c.type == "Ready" and c.status == "True" for c in conditions):
            return
        time.sleep(2)
    raise RuntimeError(f"Sandbox {sandbox_id} never became healthy")


def wait_for_pod_exec_output(
    client: "k8s_client_module.CoreV1Api",
    pod_name: str,
    output_path: str,
    timeout_s: float,
    namespace: str = SANDBOX_NAMESPACE,
    container: str = "sandbox",
) -> PodExecResult:
    """Poll the ``pod_exec_async`` tempfile until it appears, returning
    ``(status_code, body)``. Raises on timeout."""
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
                return PodExecResult(status_code=int(head), body=rest)
        time.sleep(2)
    raise RuntimeError(
        f"pod_exec output {output_path} on pod {pod_name} did not arrive within "
        f"{timeout_s:.1f}s"
    )


def wait_for_proxy_redeploy(
    client: "k8s_client_module.CoreV1Api",
    timeout_s: float = 120,
) -> None:
    """Wait until the sandbox-proxy Deployment reports a ready replica."""
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
) -> PoolSession:
    """Fresh API-created session on the module pool pod; returns ``(sandbox_id, session_id, pod_name)``.

    Same shape as ``live_pod`` but reuses the pool pod. Use this unless the test
    mutates pod-level state (lifecycle/terminate/restart); those must use ``live_pod``.
    """
    _cleanup_pool_workspace(_pool_pod.k8s_client, _pool_pod.pod_name)
    session_id, sandbox_id = BuildSessionManager.create_with_sandbox(_pool_pod.api_user)
    _SUITE_SANDBOX_IDS.add(sandbox_id)
    if sandbox_id != _pool_pod.sandbox_id:
        # Pool invariant broke (pool pod terminated externally). Reap the stray and fail loudly.
        with suppress(Exception):
            _pool_pod.manager.terminate(sandbox_id)
        pytest.fail(
            f"pool_session: API returned a new sandbox {sandbox_id!r} instead "
            f"of the pool pod {_pool_pod.sandbox_id!r}; the pool pod may have "
            "been terminated externally."
        )
    return PoolSession(
        sandbox_id=sandbox_id,
        session_id=session_id,
        pod_name=_pool_pod.pod_name,
    )


@pytest.fixture(scope="function")
def live_pod(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[PoolSession, None, None]:
    """Provision a fresh sandbox + session pod, torn down on exit.

    Yields ``(sandbox_id, session_id, pod_name)``. Prefer ``pool_session``
    unless the test mutates pod-level state.
    """
    with _provisioned_sandbox(k8s_manager, k8s_client) as (
        _api_user,
        sandbox_id,
        session_id,
        pod_name,
    ):
        yield PoolSession(
            sandbox_id=sandbox_id,
            session_id=session_id,
            pod_name=pod_name,
        )


@pytest.fixture(scope="function")
def owned_live_pod(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: "k8s_client_module.CoreV1Api",
) -> Generator[OwnedLivePod, None, None]:
    """Like ``live_pod`` but also yields the owning API user for API-driven calls.

    Yields ``(api_user, sandbox_id, session_id, pod_name)``.
    """
    with _provisioned_sandbox(k8s_manager, k8s_client) as result:
        yield result


@pytest.fixture(scope="function")
def pool_api_user(_pool_pod: _PoolPod) -> "DATestUser":
    """The API user owning ``pool_session`` sessions; for API-driven snapshot/restore."""
    return _pool_pod.api_user
