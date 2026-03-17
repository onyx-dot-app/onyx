"""
Permissioning / AccessControl logic for Canvas courses.

CE stub — returns None (no permissions).
The EE implementation is loaded at runtime via fetch_versioned_implementation
when permission sync is wired up (PR4).
"""

from onyx.access.models import ExternalAccess
from onyx.connectors.canvas.client import CanvasApiClient


def get_course_permissions(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> ExternalAccess | None:
    return None
