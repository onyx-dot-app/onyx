import time
from uuid import uuid4

import pytest
from kubernetes import client

from onyx.server.features.build.sandbox.labels import (
    LABEL_K8S_MANAGED_BY,
    LABEL_SANDBOX_ID,
    LABEL_TENANT_ID,
)
from onyx.server.features.build.sandbox.models import SandboxResourceKind
from tests.common.craft.kubernetes_resources import CleanupNamespace


def test_inventory_crosses_real_kubernetes_pages_and_excludes_other_tenants(
    cleanup_namespace: CleanupNamespace,
) -> None:
    cluster = cleanup_namespace
    owner = uuid4()
    name = cluster.create(owner)
    foreign = uuid4()
    cluster.create(foreign, tenant="another-tenant")
    secret = cluster.core.read_namespaced_secret(f"{name}-opencode-auth", cluster.name)
    expected = {name, f"{name}-opencode-auth"}
    for index in range(101):
        extra_name = f"{name}-page-{index}"
        cluster.core.create_namespaced_secret(
            cluster.name,
            client.V1Secret(
                metadata=client.V1ObjectMeta(
                    name=extra_name, labels=secret.metadata.labels
                ),
                string_data={"password": "pagination-test"},
            ),
        )
        expected.add(extra_name)

    resources = list(cluster.manager.iter_resources("public", time.monotonic() + 60))

    assert {resource.name for resource in resources} == expected
    assert len(resources) == 104
    assert {resource.sandbox_id for resource in resources} == {owner}
    assert {resource.tenant_id for resource in resources} == {"public"}
    assert {resource.kind for resource in resources} == {
        SandboxResourceKind.POD,
        SandboxResourceKind.SERVICE,
        SandboxResourceKind.SECRET,
    }
    assert all(resource.instance_id for resource in resources)


def test_late_deletion_cannot_remove_a_same_name_replacement(
    cleanup_namespace: CleanupNamespace,
) -> None:
    cluster = cleanup_namespace
    owner = uuid4()
    name = f"{cluster.create(owner)}-opencode-auth"
    observed = next(
        resource
        for resource in cluster.manager.iter_resources("public", time.monotonic() + 30)
        if resource.kind == SandboxResourceKind.SECRET
    )
    old = cluster.core.read_namespaced_secret(name, cluster.name)
    cluster.core.delete_namespaced_secret(name, cluster.name)
    cluster.wait_absent("secret", name)
    replacement = cluster.core.create_namespaced_secret(
        cluster.name,
        client.V1Secret(
            metadata=client.V1ObjectMeta(name=name, labels=old.metadata.labels),
            string_data={"password": "new-instance"},
        ),
    )
    assert replacement.metadata.uid != observed.instance_id

    with pytest.raises(RuntimeError, match="ownership changed"):
        cluster.manager.delete_resource(observed, time.monotonic() + 30)

    retained = cluster.core.read_namespaced_secret(name, cluster.name)
    assert retained.metadata.uid == replacement.metadata.uid
    assert retained.metadata.deletion_timestamp is None


@pytest.mark.parametrize(
    "label",
    [
        LABEL_SANDBOX_ID,
        LABEL_TENANT_ID,
        LABEL_K8S_MANAGED_BY,
    ],
)
def test_cleanup_rechecks_ownership_against_the_live_resource(
    cleanup_namespace: CleanupNamespace, label: str
) -> None:
    cluster = cleanup_namespace
    name = f"{cluster.create(uuid4())}-opencode-auth"
    observed = next(
        resource
        for resource in cluster.manager.iter_resources("public", time.monotonic() + 30)
        if resource.kind == SandboxResourceKind.SECRET
    )
    replacement_value = str(uuid4())
    cluster.core.patch_namespaced_secret(
        name, cluster.name, {"metadata": {"labels": {label: replacement_value}}}
    )

    with pytest.raises(RuntimeError, match="ownership changed"):
        cluster.manager.delete_resource(observed, time.monotonic() + 30)

    retained = cluster.core.read_namespaced_secret(name, cluster.name)
    assert retained.metadata.uid == observed.instance_id
    assert retained.metadata.labels[label] == replacement_value
    assert retained.metadata.deletion_timestamp is None
