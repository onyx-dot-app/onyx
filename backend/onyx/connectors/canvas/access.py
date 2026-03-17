"""
Permissioning / AccessControl logic for Canvas courses.

CE stub — returns None (no permissions). Upgraded in a follow-up PR.
"""

from onyx.access.models import ExternalAccess
from onyx.connectors.canvas.client import CanvasApiClient


def get_course_permissions(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> ExternalAccess | None:
    return None
