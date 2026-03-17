"""
EE implementation: fetch Canvas course permissions from the enrollments API.

All actively enrolled users (students, teachers, TAs, designers, etc.)
are granted access to course documents.
"""

from onyx.access.models import ExternalAccess
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_course_permissions(
    canvas_client: CanvasApiClient,
    course_id: int,
) -> ExternalAccess:
    """Fetch emails for all actively enrolled users in a Canvas course.

    Calls the Canvas enrollments API with state=active (no role filter),
    paginates via Link headers, and returns an ExternalAccess
    with those emails.

    Returns ExternalAccess.empty() on failure (safe fallback —
    documents become private rather than public).
    """
    emails: set[str] = set()

    try:
        for page in canvas_client.paginate(
            f"courses/{course_id}/enrollments",
            params={"per_page": "100", "state[]": "active", "include[]": "email"},
        ):
            for enrollment in page:
                user = enrollment.get("user", {})
                email = user.get("email") or user.get("login_id")
                if email and "@" in email:
                    emails.add(email)

    except Exception as e:
        logger.warning(
            f"Failed to fetch enrollments for course {course_id}: {e}. "
            "Falling back to empty access (documents will be private)."
        )
        return ExternalAccess.empty()

    if not emails:
        logger.debug(
            f"No active enrollments found for course {course_id}"
        )
        return ExternalAccess.empty()

    return ExternalAccess(
        external_user_emails=emails,
        external_user_group_ids=set(),
        is_public=False,
    )
