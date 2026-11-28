from collections.abc import Mapping

LABEL_SANDBOX_ID = "onyx.app/sandbox-id"
LABEL_TENANT_ID = "onyx.app/tenant-id"
# Creation attempt. Cleanup compares it with the database owner before deletion.
LABEL_PROVISIONING_ATTEMPT = "onyx.app/provisioning-attempt"
LABEL_K8S_COMPONENT = "app.kubernetes.io/component"
LABEL_K8S_COMPONENT_SANDBOX = "sandbox"
LABEL_K8S_MANAGED_BY = "app.kubernetes.io/managed-by"
LABEL_K8S_MANAGED_BY_ONYX = "onyx"

# Docker-backend equivalents of the K8s component label. The proxy's
# DockerEventsLookup filters on these; ``docker_sandbox_manager`` stamps them
# onto every sandbox container it creates.
LABEL_DOCKER_COMPONENT = "onyx.app/component"
LABEL_DOCKER_COMPONENT_SANDBOX = "craft-sandbox"
LABEL_DOCKER_NETWORK = "onyx.app/sandbox-network"
LABEL_K8S_COMPONENT_AUTH = "sandbox-opencode-auth"

# Harness sandboxes carry the component labels above, so the egress proxy
# identifies them. Craft reconcile and cleanup must skip them by this label.
LABEL_SANDBOX_KIND = "onyx.app/sandbox-kind"
SANDBOX_KIND_HARNESS = "harness"
# k8s "!=" also matches objects that have no such label.
NOT_HARNESS_SELECTOR = f"{LABEL_SANDBOX_KIND}!={SANDBOX_KIND_HARNESS}"


def is_harness_resource(labels: Mapping[str, str] | None) -> bool:
    return (labels or {}).get(LABEL_SANDBOX_KIND) == SANDBOX_KIND_HARNESS
