"""Fault injection is restricted to a disposable, full Craft deployment."""

import shlex
from datetime import datetime, timedelta, timezone

import pytest
from kubernetes import client
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession, Sandbox
from onyx.server.features.build.configs import (
    SANDBOX_BACKEND,
    SANDBOX_IDLE_TIMEOUT_SECONDS,
    SANDBOX_NAMESPACE,
    SandboxBackend,
)
from onyx.server.features.build.db.build_session import reserve_nextjs_port__no_commit
from tests.common.craft.cleanup_worker import (
    isolated_cleanup_deployment as isolated_cleanup_deployment,
)
from tests.common.craft.cleanup_worker import (
    require_isolated_cleanup_deployment,
    run_cleanup,
)
from tests.integration.tests.craft.k8s.k8s_fixtures import OwnedLivePod, pod_exec

require_isolated_cleanup_deployment()
pytestmark = [
    pytest.mark.skipif(
        SANDBOX_BACKEND != SandboxBackend.KUBERNETES, reason="Kubernetes only"
    ),
    pytest.mark.usefixtures("isolated_cleanup_deployment", "tenant_context"),
]


@pytest.mark.parametrize("failure", ["workspace-discovery", "history-snapshot"])
def test_worker_preserves_files_runtime_and_ports_after_checkpoint_failure(
    owned_live_pod: OwnedLivePod,
    k8s_client: client.CoreV1Api,
    db_session: Session,
    failure: str,
) -> None:
    owned = owned_live_pod
    pod = k8s_client.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE)
    path = f"/workspace/sessions/{owned.session_id}/outputs/retained.txt"
    pod_exec(
        k8s_client, owned.pod_name, SANDBOX_NAMESPACE, f"printf retained-work > {path}"
    )
    session = db_session.get(BuildSession, owned.session_id)
    assert session is not None
    if session.nextjs_port is None:
        reserve_nextjs_port__no_commit(db_session, session)
        db_session.commit()
    original_port = session.nextjs_port
    assert original_port is not None
    if failure == "workspace-discovery":
        blocked_path = "/workspace/sessions"
    else:
        blocked_path = pod_exec(
            k8s_client,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            "find /workspace/opencode-data -name '*.db' -type f -print -quit",
            container="sidecar",
        ).strip()
        assert blocked_path.startswith("/workspace/opencode-data/"), blocked_path
    blocked_path = shlex.quote(blocked_path)
    original_mode = pod_exec(
        k8s_client,
        owned.pod_name,
        SANDBOX_NAMESPACE,
        f"stat -c %a {blocked_path}",
        container="sidecar",
    ).strip()
    assert original_mode.isdigit(), original_mode
    try:
        pod_exec(
            k8s_client,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            f"chmod 000 {blocked_path}",
            container="sidecar",
        )
        sandbox = db_session.get(Sandbox, owned.sandbox_id)
        assert sandbox is not None
        sandbox.last_heartbeat = datetime.now(timezone.utc) - timedelta(
            seconds=SANDBOX_IDLE_TIMEOUT_SECONDS + 60
        )
        db_session.commit()

        run_cleanup(k8s_client)

        db_session.expire_all()
        db_session.refresh(sandbox)
        db_session.refresh(session)
        assert sandbox.status == SandboxStatus.RUNNING
        assert sandbox.cleanup_checkpoint is None
        assert session.nextjs_port == original_port
        surviving = k8s_client.read_namespaced_pod(owned.pod_name, SANDBOX_NAMESPACE)
        assert surviving.metadata.uid == pod.metadata.uid
        assert surviving.metadata.deletion_timestamp is None
    finally:
        pod_exec(
            k8s_client,
            owned.pod_name,
            SANDBOX_NAMESPACE,
            f"chmod {original_mode} {blocked_path}",
            container="sidecar",
        )
    assert (
        pod_exec(k8s_client, owned.pod_name, SANDBOX_NAMESPACE, f"cat {path}").strip()
        == "retained-work"
    )
