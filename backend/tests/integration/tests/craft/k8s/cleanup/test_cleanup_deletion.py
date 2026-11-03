from uuid import uuid4

import pytest
from kubernetes import client

from tests.common.craft.kubernetes_resources import TEST_FINALIZER, CleanupNamespace


def test_service_finalizer_does_not_report_complete_or_skip_other_resources(
    cleanup_namespace: CleanupNamespace,
) -> None:
    cluster = cleanup_namespace
    sandbox_id = uuid4()
    name = cluster.create(sandbox_id)
    cluster.core.patch_namespaced_service(
        name, cluster.name, {"metadata": {"finalizers": [TEST_FINALIZER]}}
    )

    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        cluster.manager.terminate(sandbox_id)

    service = cluster.core.read_namespaced_service(name, cluster.name)
    assert service.metadata.deletion_timestamp is not None
    assert service.metadata.finalizers == [TEST_FINALIZER]
    cluster.wait_absent("pod", name)
    cluster.wait_absent("secret", f"{name}-opencode-auth")

    cluster.core.patch_namespaced_service(
        name, cluster.name, {"metadata": {"finalizers": None}}
    )
    cluster.wait_absent("service", name)
    cluster.manager.terminate(sandbox_id)


def test_cleanup_can_resume_when_only_service_and_secret_remain(
    cleanup_namespace: CleanupNamespace,
) -> None:
    cluster = cleanup_namespace
    sandbox_id = uuid4()
    name = cluster.create(sandbox_id)
    cluster.core.delete_namespaced_pod(
        name, cluster.name, body=client.V1DeleteOptions(grace_period_seconds=0)
    )
    cluster.wait_absent("pod", name)

    cluster.manager.terminate(sandbox_id)

    assert cluster.absent("service", name)
    assert cluster.absent("secret", f"{name}-opencode-auth")
