"""
Permissioning / AccessControl logic for Canvas courses.
"""

from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version


def get_course_permissions(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> ExternalAccess | None:
    """
    Fetch course-level permissions based on enrollment.
    This functionality requires Enterprise Edition.

    Args:
        canvas_client: The Canvas API client instance.
        course_id: The Canvas course ID.

    Returns:
        ExternalAccess object for the course. None if EE is not enabled.
    """

    if not global_version.is_ee_version():
        return None

    ee_get_course_permissions = cast(
        Callable[
            [CanvasApiClient, int],
            ExternalAccess | None,
        ],
        fetch_versioned_implementation(
            "onyx.external_permissions.canvas.access", "get_course_permissions"
        ),
    )

    return ee_get_course_permissions(
        canvas_client,
        course_id,
    )
