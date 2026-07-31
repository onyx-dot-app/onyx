from uuid import UUID

from onyx.utils.logger import setup_logger

logger = setup_logger()

LABEL_SANDBOX_ID = "onyx.app/sandbox-id"
LABEL_TENANT_ID = "onyx.app/tenant-id"
# Provisioning attempt that created the resource. Operator-facing orphan
# attribution only (kubectl/docker inspect) — never read programmatically;
# correctness comes from the attempt-number condition on sandbox status writes.
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


def parse_sandbox_id(raw: str | None) -> UUID | None:
    """The sandbox a labelled resource belongs to, or None if it names none.

    Both backends scan their fleet by this label, and neither can do anything
    with a resource it cannot tie to a sandbox — so an unparseable value is
    dropped rather than raised, and never fails the surrounding scan.
    """
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        logger.warning("Sandbox resource carries an unparseable id label %r", raw)
        return None
