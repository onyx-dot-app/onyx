from uuid import uuid4

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from tests.common.craft.kubernetes_resources import CleanupNamespace


def test_deployed_sandbox_manager_service_accounts_can_inventory_resources(
    k8s_client: client.CoreV1Api,
) -> None:
    rbac = client.RbacAuthorizationV1Api(k8s_client.api_client)
    authorization = client.AuthorizationV1Api(k8s_client.api_client)
    bindings = [
        binding
        for binding in rbac.list_namespaced_role_binding(SANDBOX_NAMESPACE).items
        if binding.role_ref.kind == "Role"
        and binding.role_ref.name.endswith("sandbox-manager")
    ]
    assert bindings, "The deployed chart has no sandbox-manager RoleBinding"
    checked = 0
    for binding in bindings:
        role = rbac.read_namespaced_role(binding.role_ref.name, SANDBOX_NAMESPACE)
        for resource in ("pods", "services", "secrets"):
            assert any(
                resource in rule.resources and "list" in rule.verbs
                for rule in role.rules
            )
            for subject in binding.subjects:
                if subject.kind != "ServiceAccount":
                    continue
                review = authorization.create_subject_access_review(
                    client.V1SubjectAccessReview(
                        spec=client.V1SubjectAccessReviewSpec(
                            user=f"system:serviceaccount:{subject.namespace or SANDBOX_NAMESPACE}:{subject.name}",
                            resource_attributes=client.V1ResourceAttributes(
                                namespace=SANDBOX_NAMESPACE,
                                verb="list",
                                resource=resource,
                            ),
                        )
                    )
                )
                assert review.status.allowed, (
                    f"{subject.name} cannot list {resource}: {review.status.reason}"
                )
                checked += 1
    assert checked >= 3


def test_real_service_delete_denial_does_not_skip_pod_or_secret(
    cleanup_namespace: CleanupNamespace,
) -> None:
    cluster = cleanup_namespace
    sandbox_id = uuid4()
    name = cluster.create(sandbox_id)
    identity = f"cleanup-denied-{uuid4().hex}"
    rbac = client.RbacAuthorizationV1Api(cluster.core.api_client)
    rbac.create_namespaced_role(
        cluster.name,
        client.V1Role(
            metadata=client.V1ObjectMeta(name="partial-cleanup"),
            rules=[
                client.V1PolicyRule(
                    api_groups=[""],
                    resources=["pods", "secrets"],
                    verbs=["get", "delete"],
                ),
                client.V1PolicyRule(
                    api_groups=[""], resources=["services"], verbs=["get"]
                ),
            ],
        ),
    )
    rbac.create_namespaced_role_binding(
        cluster.name,
        client.V1RoleBinding(
            metadata=client.V1ObjectMeta(name="partial-cleanup"),
            role_ref=client.V1RoleRef(
                api_group="rbac.authorization.k8s.io",
                kind="Role",
                name="partial-cleanup",
            ),
            subjects=[
                client.RbacV1Subject(
                    kind="User", name=identity, api_group="rbac.authorization.k8s.io"
                )
            ],
        ),
    )
    original = cluster.manager._core_api
    with client.ApiClient(
        client.Configuration.get_default_copy(),
        header_name="Impersonate-User",
        header_value=identity,
    ) as api:
        cluster.manager._core_api = client.CoreV1Api(api)
        try:
            with pytest.raises(RuntimeError, match="cleanup incomplete") as error:
                cluster.manager.terminate(sandbox_id)
            assert isinstance(error.value.__cause__, ApiException)
            assert error.value.__cause__.status == 403
        finally:
            cluster.manager._core_api = original
    cluster.wait_absent("pod", name)
    cluster.wait_absent("secret", f"{name}-opencode-auth")
    retained = cluster.core.read_namespaced_service(name, cluster.name)
    assert retained.metadata.deletion_timestamp is None

    cluster.manager.terminate(sandbox_id)
    assert cluster.absent("service", name)
