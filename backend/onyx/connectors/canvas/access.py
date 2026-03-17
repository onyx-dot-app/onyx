"""
Permissioning / AccessControl logic for Canvas courses.

Stub implementation — returns None (no permissions).
Full implementation added when permission sync is wired up.
"""

from onyx.access.models import ExternalAccess
from onyx.connectors.canvas.client import CanvasApiClient


def get_course_permissions(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> ExternalAccess | None:
    return None
