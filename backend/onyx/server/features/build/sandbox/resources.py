import time
from datetime import datetime

from pydantic import ValidationError

from onyx.server.features.build.sandbox.labels import (
    LABEL_PROVISIONING_ATTEMPT,
    LABEL_SANDBOX_ID,
    LABEL_TENANT_ID,
)
from onyx.server.features.build.sandbox.models import (
    SandboxResource,
    SandboxResourceKind,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def remaining_request_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Sandbox resource operation deadline exceeded")
    return min(remaining, 15.0)


def sandbox_resource_from_labels(
    *,
    kind: SandboxResourceKind,
    name: str,
    instance_id: str,
    created_at: datetime | str,
    labels: dict[str, str],
    tenant_id: str,
) -> SandboxResource | None:
    if labels.get(LABEL_TENANT_ID) != tenant_id or not instance_id:
        return None
    try:
        resource = SandboxResource.model_validate(
            {
                "kind": kind,
                "name": name,
                "instance_id": instance_id,
                "created_at": created_at,
                "sandbox_id": labels.get(LABEL_SANDBOX_ID),
                "tenant_id": tenant_id,
                "provisioning_attempt_number": labels.get(LABEL_PROVISIONING_ATTEMPT),
            }
        )
        if resource.created_at.tzinfo is None:
            raise ValueError("Resource creation time has no timezone")
        return resource
    except (ValueError, ValidationError):
        logger.warning("Skipping resource %s with invalid ownership metadata", name)
        return None
