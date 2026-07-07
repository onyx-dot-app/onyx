from typing import Any

from pydantic import BaseModel
from pydantic import Field

from onyx.access.models import ExternalAccess
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.connectors.canvas.connector import canvas_all_users_group_id
from onyx.connectors.canvas.connector import canvas_course_group_id
from onyx.connectors.canvas.connector import canvas_group_group_id
from onyx.connectors.canvas.connector import canvas_section_group_id
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ACTIVE_ENROLLMENT_STATES = {"active", "invited"}
_STAFF_ENROLLMENT_TYPES = {
    "TeacherEnrollment",
    "TaEnrollment",
    "DesignerEnrollment",
}


class CanvasCoursePermissionContext(BaseModel):
    course_id: int
    user_id_to_email: dict[int, str] = Field(default_factory=dict)
    section_id_to_emails: dict[int, set[str]] = Field(default_factory=dict)
    staff_emails: set[str] = Field(default_factory=set)
    is_public: bool = False
    can_use_all_users_group: bool = False


def _active_enrollments(user: dict[str, Any]) -> list[dict[str, Any]]:
    enrollments = user.get("enrollments") or []
    return [
        enrollment
        for enrollment in enrollments
        if isinstance(enrollment, dict)
        and enrollment.get("enrollment_state") in _ACTIVE_ENROLLMENT_STATES
    ]


def _fetch_course(canvas_client: CanvasApiClient, course_id: int) -> dict[str, Any]:
    course, _ = canvas_client.get(f"courses/{course_id}")
    if not isinstance(course, dict):
        return {}
    return course


def _fetch_course_users(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    for page in canvas_client.paginate(
        f"courses/{course_id}/users",
        params={
            "per_page": "100",
            "include[]": ["email", "enrollments"],
            "enrollment_state[]": list(_ACTIVE_ENROLLMENT_STATES),
        },
    ):
        users.extend(user for user in page if isinstance(user, dict))
    return users


def can_list_account_users(canvas_client: CanvasApiClient) -> bool:
    try:
        canvas_client.get(
            "accounts/self/users",
            params={"per_page": "1", "include[]": "email"},
        )
        return True
    except OnyxError as e:
        if e.status_code in (401, 403):
            logger.warning(
                "Canvas token cannot enumerate account users. Public Canvas courses "
                "will be permissioned to their course roster only."
            )
            return False
        raise


def build_course_permission_context(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> CanvasCoursePermissionContext:
    course = _fetch_course(canvas_client, course_id)
    users = _fetch_course_users(canvas_client, course_id)
    is_public = bool(course.get("is_public") or course.get("is_public_to_auth_users"))
    context = CanvasCoursePermissionContext(
        course_id=course_id,
        is_public=is_public,
        can_use_all_users_group=is_public and can_list_account_users(canvas_client),
    )

    for user in users:
        email = user.get("email")
        user_id = user.get("id")
        if not email or not isinstance(user_id, int):
            continue

        context.user_id_to_email[user_id] = email
        for enrollment in _active_enrollments(user):
            if enrollment.get("type") in _STAFF_ENROLLMENT_TYPES:
                context.staff_emails.add(email)

            section_id = enrollment.get("course_section_id")
            if isinstance(section_id, int):
                context.section_id_to_emails.setdefault(section_id, set()).add(email)

    return context


def _course_group_access(context: CanvasCoursePermissionContext) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={canvas_course_group_id(context.course_id)},
        is_public=False,
    )


def _add_public_course_groups(
    context: CanvasCoursePermissionContext,
    access: ExternalAccess,
) -> ExternalAccess:
    if not context.is_public:
        return access

    group_ids = set(access.external_user_group_ids)
    group_ids.add(canvas_course_group_id(context.course_id))
    if context.can_use_all_users_group:
        group_ids.add(canvas_all_users_group_id())

    return ExternalAccess(
        external_user_emails=set(access.external_user_emails),
        external_user_group_ids=group_ids,
        is_public=False,
    )


def _restricted_access(
    context: CanvasCoursePermissionContext,
    group_ids: set[str],
    user_emails: set[str] | None = None,
) -> ExternalAccess:
    return _add_public_course_groups(
        context,
        ExternalAccess(
            external_user_emails=set(user_emails or set()) | context.staff_emails,
            external_user_group_ids=group_ids,
            is_public=False,
        ),
    )


def get_course_permissions(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> ExternalAccess:
    return get_page_permissions(
        build_course_permission_context(canvas_client, course_id)
    )


def get_page_permissions(context: CanvasCoursePermissionContext) -> ExternalAccess:
    return _add_public_course_groups(context, _course_group_access(context))


def get_assignment_permissions(
    context: CanvasCoursePermissionContext,
    assignment: Any,
) -> ExternalAccess:
    if not assignment.only_visible_to_overrides:
        return get_page_permissions(context)

    group_ids: set[str] = set()
    user_emails: set[str] = set()
    for override in assignment.overrides:
        if override.course_section_id is not None:
            group_ids.add(canvas_section_group_id(override.course_section_id))
        if override.group_id is not None:
            group_ids.add(canvas_group_group_id(override.group_id))
        user_emails.update(
            email
            for user_id in override.student_ids
            if (email := context.user_id_to_email.get(user_id))
        )

    user_emails.update(
        email
        for user_id in assignment.assignment_visibility
        if (email := context.user_id_to_email.get(user_id))
    )

    return _restricted_access(context, group_ids, user_emails)


def get_announcement_permissions(
    context: CanvasCoursePermissionContext,
    announcement: Any,
) -> ExternalAccess:
    if not announcement.is_section_specific:
        return get_page_permissions(context)

    section_group_ids = {
        canvas_section_group_id(section.id) for section in announcement.sections
    }
    return _restricted_access(context, section_group_ids)
