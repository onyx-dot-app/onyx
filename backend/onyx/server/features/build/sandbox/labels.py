from onyx.server.features.build.sandbox.image.guest import PROTOCOL_VERSION

LABEL_SANDBOX_ID = "onyx.app/sandbox-id"
LABEL_TENANT_ID = "onyx.app/tenant-id"
# Provisioning attempt that created the resource, for operator orphan attribution.
# Never read programmatically. Sandbox status writes enforce the attempt number.
LABEL_PROVISIONING_ATTEMPT = "onyx.app/provisioning-attempt"
LABEL_SANDBOX_PROTOCOL = "onyx.app/sandbox-protocol"
SANDBOX_PROTOCOL_VERSION = str(PROTOCOL_VERSION)
LABEL_K8S_COMPONENT = "app.kubernetes.io/component"
LABEL_K8S_COMPONENT_SANDBOX = "sandbox"
LABEL_K8S_MANAGED_BY = "app.kubernetes.io/managed-by"
LABEL_K8S_MANAGED_BY_ONYX = "onyx"
