"""Guards the admin site-wide announcement's delivery contract: it is
materialized per-user as a SYSTEM_ANNOUNCEMENT notification on read, editing it
re-shows it to users who dismissed the prior version, and deleting it clears it
for everyone.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.admin_banner import clear_admin_banner
from onyx.db.admin_banner import get_admin_banner
from onyx.db.admin_banner import set_admin_banner
from onyx.db.models import UserRole
from onyx.db.notification import get_notifications
from onyx.server.features.admin_banner import api as admin_banner_api
from onyx.server.features.admin_banner.api import AdminBannerUpdateRequest
from onyx.server.features.notifications import api as notifications_api
from onyx.server.features.notifications.utils import (
    ensure_system_announcement_notification,
)
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture(autouse=True)
def _clear_banner_between_tests(
    db_session: Session,  # noqa: ARG001 (initializes the DB engine before the KV clear)
    tenant_context: None,  # noqa: ARG001 (keeps the KV clear inside the test tenant)
) -> Generator[None, None, None]:
    # The banner is one global KV value in the shared default tenant, so a leak
    # would synthesize a stray notification in every other test's read path.
    clear_admin_banner()
    try:
        yield
    finally:
        clear_admin_banner()


def _system_announcements(user: object, db_session: Session) -> list:
    return get_notifications(
        user=user,  # ty: ignore[invalid-argument-type]
        db_session=db_session,
        notif_type=NotificationType.SYSTEM_ANNOUNCEMENT,
        include_dismissed=True,
    )


def test_ensure_creates_notification_and_is_idempotent(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "sys_announce_create")
    set_admin_banner(title="Bedrock degraded", content="Working on it.")

    ensure_system_announcement_notification(user, db_session)
    ensure_system_announcement_notification(user, db_session)

    rows = _system_announcements(user, db_session)
    assert len(rows) == 1
    assert rows[0].title == "Bedrock degraded"
    assert rows[0].description == "Working on it."
    assert rows[0].dismissed is False


def test_ensure_is_noop_when_no_banner(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "sys_announce_noop")

    ensure_system_announcement_notification(user, db_session)

    assert _system_announcements(user, db_session) == []


def test_get_notifications_api_synthesizes_system_announcement(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "sys_announce_api")
    set_admin_banner(title="Scheduled maintenance", content=None)

    response = notifications_api.get_notifications_api(
        page_num=0,
        page_size=50,
        notif_type=NotificationType.SYSTEM_ANNOUNCEMENT,
        user=user,
        db_session=db_session,
    )

    assert response.total_items == 1
    assert response.undismissed_count == 1
    assert response.notifications[0].title == "Scheduled maintenance"


def test_upsert_wipes_prior_rows_so_edit_reshows(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    admin = create_test_user(db_session, "sys_announce_edit", role=UserRole.ADMIN)
    set_admin_banner(title="v1 title", content="v1 body")
    ensure_system_announcement_notification(admin, db_session)

    row = _system_announcements(admin, db_session)[0]
    row.dismissed = True
    db_session.commit()

    edited = admin_banner_api.upsert_admin_banner(
        AdminBannerUpdateRequest(title="v2 title", content="v2 body"),
        admin,
        db_session,
    )
    assert edited.title == "v2 title"
    # The dismissed row is gone after the edit, so the reader re-materializes it.
    assert _system_announcements(admin, db_session) == []

    ensure_system_announcement_notification(admin, db_session)
    rows = _system_announcements(admin, db_session)
    assert len(rows) == 1
    assert rows[0].dismissed is False
    assert rows[0].title == "v2 title"


def test_delete_clears_banner_and_notifications(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    admin = create_test_user(db_session, "sys_announce_delete", role=UserRole.ADMIN)
    set_admin_banner(title="Temporary notice", content="Ends soon.")
    ensure_system_announcement_notification(admin, db_session)
    assert len(_system_announcements(admin, db_session)) == 1

    admin_banner_api.delete_admin_banner(admin, db_session)

    assert get_admin_banner() is None
    assert _system_announcements(admin, db_session) == []
    # A later read no longer re-creates it.
    ensure_system_announcement_notification(admin, db_session)
    assert _system_announcements(admin, db_session) == []


def test_upsert_stores_show_as_popup(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    admin = create_test_user(db_session, "sys_announce_popup", role=UserRole.ADMIN)
    admin_banner_api.upsert_admin_banner(
        AdminBannerUpdateRequest(
            title="Maintenance", content="Soon", show_as_popup=True
        ),
        admin,
        db_session,
    )

    stored = get_admin_banner()
    assert stored is not None
    assert stored.show_as_popup is True
