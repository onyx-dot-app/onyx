"""Convergence through the real worker, including the real resource grace period."""

import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from kubernetes import client
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.configs import (
    SANDBOX_BACKEND,
    SANDBOX_NAMESPACE,
    SandboxBackend,
)
from onyx.server.features.build.db.sandbox import get_running_sandboxes
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.session.resource_cleanup import RESOURCE_GRACE_SECONDS
from onyx.server.features.build.timeouts import ATTEMPT_DEADLINE_SECONDS
from tests.common.craft.cleanup_worker import (
    isolated_cleanup_deployment as isolated_cleanup_deployment,
)
from tests.common.craft.cleanup_worker import (
    require_isolated_cleanup_deployment,
    run_cleanup,
    wait_for_resource_grace,
)
from tests.common.craft.kubernetes_resources import CleanupNamespace
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.tests.craft.k8s.k8s_fixtures import cleanup_api_user_sandbox_rows

require_isolated_cleanup_deployment()
pytestmark = [
    pytest.mark.skipif(
        SANDBOX_BACKEND != SandboxBackend.KUBERNETES, reason="Kubernetes only"
    ),
    pytest.mark.usefixtures("isolated_cleanup_deployment", "tenant_context"),
]


def test_worker_collects_orphans_and_abandoned_provisioning_without_running_rows(
    k8s_client: client.CoreV1Api, db_session: Session
) -> None:
    manager = KubernetesSandboxManager()
    cluster = CleanupNamespace(SANDBOX_NAMESPACE, k8s_client, manager)
    failed_user = UserManager.create(name=f"cleanup-failed-{uuid4().hex[:8]}")
    stale_user = UserManager.create(name=f"cleanup-stale-{uuid4().hex[:8]}")
    failed = Sandbox(
        user_id=UUID(failed_user.id),
        status=SandboxStatus.FAILED,
        provisioning_attempt_number=1,
    )
    stale = Sandbox(
        user_id=UUID(stale_user.id),
        status=SandboxStatus.PROVISIONING,
        provisioning_attempt_number=1,
        provisioning_started_at=datetime.now(timezone.utc)
        - timedelta(seconds=ATTEMPT_DEADLINE_SECONDS + 60),
    )
    db_session.add_all([failed, stale])
    db_session.commit()
    owners = [uuid4(), failed.id, stale.id]
    foreign = uuid4()
    all_owners = [*owners, foreign]
    lease = get_cache_backend(tenant_id="public").lock(
        OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK,
        timeout=RESOURCE_GRACE_SECONDS + 1800,
    )
    try:
        for owner in owners:
            cluster.create(owner)
        foreign_name = cluster.create(foreign, tenant="another-tenant")
        assert get_running_sandboxes(db_session) == []

        run_cleanup(k8s_client)

        db_session.expire_all()
        db_session.refresh(stale)
        assert stale.status == SandboxStatus.FAILED
        for owner in owners:
            assert not cluster.absent("pod", f"sandbox-{str(owner)[:8]}")
        db_session.commit()

        assert lease.acquire(blocking=True, blocking_timeout=30)
        saved_table = f"sandbox_unavailable_{uuid4().hex}"
        try:
            wait_for_resource_grace(
                k8s_client, f"sandbox-{str(owners[2])[:8]}", SANDBOX_NAMESPACE
            )
            db_session.execute(text(f'ALTER TABLE sandbox RENAME TO "{saved_table}"'))
            db_session.commit()
        finally:
            if lease.owned():
                lease.release()

        try:
            run_cleanup(k8s_client, expected_state="FAILURE")
            for owner in owners:
                assert not cluster.absent("pod", f"sandbox-{str(owner)[:8]}")
        finally:
            db_session.rollback()
            db_session.execute(text(f'ALTER TABLE "{saved_table}" RENAME TO sandbox'))
            db_session.commit()

        run_cleanup(k8s_client)

        for owner in owners:
            name = f"sandbox-{str(owner)[:8]}"
            cluster.wait_absent("pod", name)
            cluster.wait_absent("service", name)
            cluster.wait_absent("secret", f"{name}-opencode-auth")
        assert not cluster.absent("pod", foreign_name)
        assert not cluster.absent("service", foreign_name)
        assert not cluster.absent("secret", f"{foreign_name}-opencode-auth")
    finally:
        if lease.owned():
            lease.release()
        for owner in all_owners:
            tenant = "another-tenant" if owner == foreign else "public"
            for resource in manager.iter_resources(tenant, time.monotonic() + 30):
                if resource.sandbox_id == owner:
                    manager.delete_resource(resource, time.monotonic() + 30)
        cleanup_api_user_sandbox_rows(UUID(failed_user.id))
        cleanup_api_user_sandbox_rows(UUID(stale_user.id))
