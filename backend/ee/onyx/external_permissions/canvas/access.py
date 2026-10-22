"""
EE implementation: resolve Canvas course permissions from LTI or REST rosters.

All actively enrolled users (students, teachers, TAs, designers, etc.)
are granted access to course documents.
"""

from typing import Any

from ee.onyx.db.user_group import fetch_lti_course_nrps_url
from onyx.access.models import ExternalAccess
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.lti.nrps import fetch_nrps_roster
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _user_email(user: dict[str, Any]) -> str | None:
    for field in ("email", "login_id"):
        value = user.get(field)
        if isinstance(value, str) and "@" in value:
            return value.strip().lower()
    return None


def get_course_permissions(
    canvas_client: CanvasApiClient,
    course_id: int,
    lti_context_id: str | None = None,
) -> ExternalAccess:
    """Fetch emails for all actively enrolled users in a Canvas course.

    LTI courses use the verified launch's NRPS roster, which supplies emails
    independently of the instructor's access to other users' Canvas profiles.
    Other connectors paginate the Canvas enrollments API with state=active
    (no role filter) and resolve email addresses from the enrolled users.

    Enrollment records do not support include[]=email. Resolve users whose
    login is not an email through the user-details API instead. A failed or
    incomplete roster must abort the sync, not replace existing permissions
    with empty or partial access.
    """
    if lti_context_id:
        nrps_url = fetch_lti_course_nrps_url(lti_context_id)
        if not nrps_url:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "The Canvas course has no LTI roster endpoint. Launch Onyx from "
                "the course with Names and Role Provisioning enabled, then sync again.",
            )
        roster = fetch_nrps_roster(nrps_url)
        # Match LTI group membership: inactive users and identities without an
        # email (including Canvas Student View) cannot receive email-based access.
        return ExternalAccess(
            external_user_emails=roster.active_member_emails(),
            external_user_group_ids=set(),
            is_public=False,
        )

    emails: set[str] = set()

    for page in canvas_client.paginate(
        f"courses/{course_id}/enrollments",
        params={"per_page": "100", "state[]": "active"},
    ):
        for enrollment in page:
            # Canvas's synthetic Test Student has no email identity to grant access.
            if enrollment.get("type") == "StudentViewEnrollment":
                continue
            user = enrollment.get("user") or {}
            email = _user_email(user)
            if email is None:
                user_id = enrollment.get("user_id") or user.get("id")
                if isinstance(user_id, int) and user_id > 0:
                    details, _ = canvas_client.get(f"users/{user_id}")
                    if isinstance(details, dict):
                        email = _user_email(details)
            if email is None:
                raise OnyxError(
                    OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                    f"Cannot resolve an active enrollment's email for Canvas course "
                    f"{course_id}. Check the connected account's roster permissions "
                    "and access to the Canvas user-details API, then sync again.",
                )
            emails.add(email)

    if not emails:
        logger.debug(f"No active enrollments found for course {course_id}")
        return ExternalAccess.empty()

    return ExternalAccess(
        external_user_emails=emails,
        external_user_group_ids=set(),
        is_public=False,
    )
