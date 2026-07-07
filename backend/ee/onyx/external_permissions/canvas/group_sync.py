from collections.abc import Generator
from typing import Any

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.canvas.access import build_course_permission_context
from onyx.connectors.canvas.connector import canvas_all_users_group_id
from onyx.connectors.canvas.connector import canvas_course_group_id
from onyx.connectors.canvas.connector import canvas_group_group_id
from onyx.connectors.canvas.connector import canvas_section_group_id
from onyx.connectors.canvas.connector import CanvasConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _credential_json(cc_pair: ConnectorCredentialPair) -> dict[str, Any]:
    return (
        cc_pair.credential.credential_json.get_value(apply_mask=False)
        if cc_pair.credential.credential_json
        else {}
    )


def _fetch_account_user_emails(connector: CanvasConnector) -> set[str]:
    user_emails: set[str] = set()
    for page in connector.canvas_client.paginate(
        "accounts/self/users",
        params={"per_page": "100", "include[]": "email"},
    ):
        for user in page:
            if isinstance(user, dict) and user.get("email"):
                user_emails.add(user["email"])
    return user_emails


def _fetch_canvas_group_emails(
    connector: CanvasConnector,
    group_id: int,
) -> set[str]:
    user_emails: set[str] = set()
    for page in connector.canvas_client.paginate(
        f"groups/{group_id}/users",
        params={"per_page": "100", "include[]": "email"},
    ):
        for user in page:
            if isinstance(user, dict) and user.get("email"):
                user_emails.add(user["email"])
    return user_emails


def _referenced_canvas_group_ids(
    connector: CanvasConnector,
    course_id: int,
) -> set[int]:
    group_ids: set[int] = set()
    for assignment in connector._list_assignments(course_id):
        for override in assignment.overrides:
            if override.group_id is not None:
                group_ids.add(override.group_id)
    return group_ids


def _referenced_section_ids(
    connector: CanvasConnector,
    course_id: int,
) -> set[int]:
    section_ids: set[int] = set()
    for assignment in connector._list_assignments(course_id):
        for override in assignment.overrides:
            if override.course_section_id is not None:
                section_ids.add(override.course_section_id)

    for announcement in connector._list_announcements(course_id):
        for section in announcement.sections:
            section_ids.add(section.id)

    return section_ids


def canvas_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector = CanvasConnector(**cc_pair.connector.connector_specific_config)
    connector.load_credentials(_credential_json(cc_pair))

    should_emit_all_users = False
    for course in connector._list_courses():
        context = build_course_permission_context(connector.canvas_client, course.id)
        course_emails = set(context.user_id_to_email.values())
        yield ExternalUserGroup(
            id=canvas_course_group_id(course.id),
            user_emails=list(course_emails),
        )

        section_ids = set(context.section_id_to_emails) | _referenced_section_ids(
            connector,
            course.id,
        )
        for section_id in section_ids:
            yield ExternalUserGroup(
                id=canvas_section_group_id(section_id),
                user_emails=list(context.section_id_to_emails.get(section_id, set())),
            )

        for group_id in _referenced_canvas_group_ids(connector, course.id):
            yield ExternalUserGroup(
                id=canvas_group_group_id(group_id),
                user_emails=list(_fetch_canvas_group_emails(connector, group_id)),
            )

        should_emit_all_users = should_emit_all_users or context.is_public

    if not should_emit_all_users:
        return

    try:
        yield ExternalUserGroup(
            id=canvas_all_users_group_id(),
            user_emails=list(_fetch_account_user_emails(connector)),
        )
    except OnyxError as e:
        if e.status_code in (401, 403):
            logger.warning(
                "Canvas token cannot enumerate account users. Public Canvas courses "
                "will be permissioned to their course roster only."
            )
            return
        raise
