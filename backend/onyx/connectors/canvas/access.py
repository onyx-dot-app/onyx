from collections.abc import Callable
from typing import Any, cast

from onyx.access.models import ExternalAccess
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)


def get_course_permissions(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> ExternalAccess | None:
    if not global_version.is_ee_version():
        return None

    ee_get_course_permissions = cast(
        Callable[[CanvasApiClient, int], ExternalAccess | None],
        fetch_versioned_implementation(
            "onyx.external_permissions.canvas.access",
            "get_course_permissions",
        ),
    )

    return ee_get_course_permissions(canvas_client, course_id)


def build_course_permission_context(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> Any | None:
    if not global_version.is_ee_version():
        return None

    ee_build_course_permission_context = cast(
        Callable[[CanvasApiClient, int], Any],
        fetch_versioned_implementation(
            "onyx.external_permissions.canvas.access",
            "build_course_permission_context",
        ),
    )

    return ee_build_course_permission_context(canvas_client, course_id)


def get_page_permissions(course_context: Any) -> ExternalAccess | None:
    if not global_version.is_ee_version():
        return None

    ee_get_page_permissions = cast(
        Callable[[Any], ExternalAccess],
        fetch_versioned_implementation(
            "onyx.external_permissions.canvas.access",
            "get_page_permissions",
        ),
    )

    return ee_get_page_permissions(course_context)


def get_assignment_permissions(
    course_context: Any,
    assignment: Any,
) -> ExternalAccess | None:
    if not global_version.is_ee_version():
        return None

    ee_get_assignment_permissions = cast(
        Callable[[Any, Any], ExternalAccess],
        fetch_versioned_implementation(
            "onyx.external_permissions.canvas.access",
            "get_assignment_permissions",
        ),
    )

    return ee_get_assignment_permissions(course_context, assignment)


def get_announcement_permissions(
    course_context: Any,
    announcement: Any,
) -> ExternalAccess | None:
    if not global_version.is_ee_version():
        return None

    ee_get_announcement_permissions = cast(
        Callable[[Any, Any], ExternalAccess],
        fetch_versioned_implementation(
            "onyx.external_permissions.canvas.access",
            "get_announcement_permissions",
        ),
    )

    return ee_get_announcement_permissions(course_context, announcement)
