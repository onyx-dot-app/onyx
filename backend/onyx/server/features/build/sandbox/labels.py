import re

from onyx import __version__
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
# Release that provisioned the sandbox. Sandbox images ship with the
# application, so a sandbox stamped with anything but the running release is on
# the image that shipped with an earlier one.
LABEL_RELEASE = "onyx.app/release"

# A Kubernetes label value: 63 chars of alphanumerics, dashes, underscores and
# dots, starting and ending alphanumeric.
_LABEL_VALUE = re.compile(r"[A-Za-z0-9]([-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$")


def current_release_label() -> str | None:
    """This process's release as a label value, or None if it cannot be one.

    One function for both sides — the backends stamp what it returns and the
    sweep compares against it — so a version that has to be adjusted to be a
    legal label can never read as stale against its own sandboxes.

    None disables the comparison rather than failing a provision: a version we
    cannot express is a reason to leave sandboxes alone, not to stop creating
    them.

    Local builds carry a constant version ("Development", "0.0.0-dev") — a
    legal value that always compares equal, so recycling is inert in local dev.
    """
    if _LABEL_VALUE.match(__version__):
        return __version__
    logger.warning(
        "Version %r cannot be a label value; sandbox release recycling is off",
        __version__,
    )
    return None


# Docker-backend equivalents of the K8s component label. The proxy's
# DockerEventsLookup filters on these; ``docker_sandbox_manager`` stamps them
# onto every sandbox container it creates.
LABEL_DOCKER_COMPONENT = "onyx.app/component"
LABEL_DOCKER_COMPONENT_SANDBOX = "craft-sandbox"
