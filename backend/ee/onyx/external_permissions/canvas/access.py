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
                # "email" is the primary field, but Canvas only returns it
                # when the token is allowed to see it (an admin token is) and
                # the user has one set. We fall back to "login_id" since most
                # instances use email as the login; the "@" check makes sure a
                # login_id fallback is actually an email.
                email = user.get("email") or user.get("login_id")
                if email and "@" in email:
                    # Normalize case: ext-perm users are created lowercased,
                    # and ACL matching is case-sensitive, so a mixed-case
                    # address here would never match the stored user.
                    emails.add(email.lower())

    except Exception as e:
        logger.warning(
            "Failed to fetch enrollments for course %s: %s. "
            "Falling back to empty access (documents will be private).",
            course_id,
            e,
        )
        return ExternalAccess.empty()

    if not emails:
        logger.debug("No active enrollments found for course %s", course_id)
        return ExternalAccess.empty()

    return ExternalAccess(
        external_user_emails=emails,
        external_user_group_ids=set(),
        is_public=False,
    )
