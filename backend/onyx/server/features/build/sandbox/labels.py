LABEL_SANDBOX_ID = "onyx.app/sandbox-id"
LABEL_TENANT_ID = "onyx.app/tenant-id"
# Provisioning attempt that currently owns the runtime: stamped at creation
# and restamped when a later attempt reuses the pod. Guarded deletes refuse to
# destroy a runtime owned by a newer attempt; DB status writes remain the
# primary fence. Also serves operator-facing orphan attribution.
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
