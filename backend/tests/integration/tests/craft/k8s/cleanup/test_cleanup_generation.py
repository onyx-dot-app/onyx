import time
from uuid import uuid4

import pytest

from onyx.server.features.build.sandbox.labels import LABEL_PROVISIONING_ATTEMPT
from onyx.server.features.build.sandbox.models import SandboxResourceKind
from tests.common.craft.kubernetes_resources import CleanupNamespace


def test_late_cleanup_cannot_delete_a_resource_claimed_by_a_newer_attempt(
    cleanup_namespace: CleanupNamespace,
) -> None:
    cluster = cleanup_namespace
    name = f"{cluster.create(uuid4(), attempt=1)}-opencode-auth"
    observed = next(
        resource
        for resource in cluster.manager.iter_resources("public", time.monotonic() + 30)
        if resource.kind == SandboxResourceKind.SECRET
    )
    assert observed.provisioning_attempt_number == 1
    cluster.core.patch_namespaced_secret(
        name, cluster.name, {"metadata": {"labels": {LABEL_PROVISIONING_ATTEMPT: "2"}}}
    )

    with pytest.raises(RuntimeError, match="ownership changed"):
        cluster.manager.delete_resource(observed, time.monotonic() + 30)

    retained = cluster.core.read_namespaced_secret(name, cluster.name)
    assert retained.metadata.uid == observed.instance_id
    assert retained.metadata.labels[LABEL_PROVISIONING_ATTEMPT] == "2"
    assert retained.metadata.deletion_timestamp is None
