import hashlib
import re
from functools import cache
from pathlib import Path

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
# Release that provisioned the sandbox. Operator-facing provenance only
# (kubectl/docker inspect) — never read programmatically: a release re-tags the
# previous sandbox image when its sources are unchanged, so recycling compares
# LABEL_SANDBOX_IMAGE, which tracks the image's content rather than its tag.
LABEL_RELEASE = "onyx.app/release"
# Content identity of the sandbox image the sandbox was provisioned on. A
# sandbox stamped with anything but the running identity is on an image whose
# sources have since changed.
LABEL_SANDBOX_IMAGE = "onyx.app/sandbox-image"

# A Kubernetes label value: 63 chars of alphanumerics, dashes, underscores and
# dots, starting and ending alphanumeric.
_LABEL_VALUE = re.compile(r"[A-Za-z0-9]([-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$")


def current_release_label() -> str | None:
    """This process's release as a label value, or None if it cannot be one.

    None skips the label rather than failing a provision: a version we cannot
    express is no reason to stop creating sandboxes.

    Local builds carry a constant version ("Development", "0.0.0-dev") — a
    legal value, so the label is stamped as usual.
    """
    if _LABEL_VALUE.match(__version__):
        return __version__
    logger.warning("Version %r cannot be a label value; not stamped", __version__)
    return None


# The build context the release pipeline builds the sandbox image from. The
# pipeline skips the build and re-tags the previous image when these files are
# unchanged, so the image's content changes exactly when they do.
_IMAGE_CONTEXT_DIR = Path(__file__).parent / "image"


@cache
def current_sandbox_image_identity() -> str | None:
    """Content identity of the sandbox image this release ships, or None.

    A hash of the image's build context, which this process carries as part of
    the backend source tree. One function for both sides — the backends stamp
    what it returns and the sweep compares against it — so a sandbox can never
    read as stale against the identity that provisioned it.

    Deliberately *not* the image tag or the release: both move every deploy,
    while the image itself changes only when its sources do. A sandbox on a
    re-tagged identical image compares equal and is left alone.

    None disables the comparison rather than failing a provision: an identity
    we cannot compute is a reason to leave sandboxes alone, not to stop
    creating them.
    """
    if not _IMAGE_CONTEXT_DIR.is_dir():
        logger.warning(
            "Sandbox image context %s is missing; sandbox image recycling is off",
            _IMAGE_CONTEXT_DIR,
        )
        return None
    digest = hashlib.sha256()
    for path in sorted(_IMAGE_CONTEXT_DIR.rglob("*")):
        # Runtime artifacts (bytecode) are not part of the build context.
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(_IMAGE_CONTEXT_DIR).as_posix()
        exec_bit = "x" if path.stat().st_mode & 0o100 else "-"
        digest.update(f"{rel}\0{exec_bit}\0".encode())
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"ctx-{digest.hexdigest()[:20]}"


# Docker-backend equivalents of the K8s component label. The proxy's
# DockerEventsLookup filters on these; ``docker_sandbox_manager`` stamps them
# onto every sandbox container it creates.
LABEL_DOCKER_COMPONENT = "onyx.app/component"
LABEL_DOCKER_COMPONENT_SANDBOX = "craft-sandbox"
