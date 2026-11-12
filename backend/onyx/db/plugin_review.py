"""Review requests for publishing plugin versions, under the admin Publishing
setting.

A request makes one version ``pending``; a plugin has at most one. A newer
request supersedes the pending one. An organization-wide plugin manager
approves (publishes) or denies a request. Approve is in ``onyx.db.skill``,
because it also writes the legacy skill row.

Callers hold the plugin lock (``lock_plugin``), after the legacy skill row
lock. Functions here flush and never commit.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, aliased

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import Permission, PluginPublishingPolicy, PluginReviewStatus
from onyx.db.models import Plugin, PluginVersion, User
from onyx.db.plugin_access import skill_name_in_version
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.settings.store import load_settings

PublishAction = Literal["publish", "request_review"]


def publish_action_for(user: User) -> PublishAction:
    """What a publish or publish update by this user does. Raises when the
    Publishing setting is OFF for the user."""
    if has_global_permission(user, Permission.MANAGE_PLUGINS):
        return "publish"
    policy = load_settings(raise_on_error=True).plugin_publishing
    if policy == PluginPublishingPolicy.OFF:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Publishing to the organization is turned off. Ask an admin to "
            "publish this skill.",
        )
    if policy == PluginPublishingPolicy.REQUIRES_REVIEW:
        return "request_review"
    return "publish"


def request_review__no_commit(
    plugin: Plugin, version_id: UUID, requested_by: User, db_session: Session
) -> None:
    """Make a version of a locked plugin the pending request. A different
    pending version becomes superseded. A published version does not change."""
    db_session.execute(
        update(PluginVersion)
        .where(
            PluginVersion.plugin_id == plugin.id,
            PluginVersion.review_status == PluginReviewStatus.PENDING,
            PluginVersion.id != version_id,
        )
        .values(review_status=PluginReviewStatus.SUPERSEDED)
    )
    db_session.execute(
        update(PluginVersion)
        .where(
            PluginVersion.id == version_id,
            PluginVersion.plugin_id == plugin.id,
            PluginVersion.review_status != PluginReviewStatus.PUBLISHED,
        )
        .values(
            review_status=PluginReviewStatus.PENDING,
            review_requested_by_user_id=requested_by.id,
            review_requested_at=func.now(),
        )
    )
    db_session.flush()


def pending_version(
    plugin: Plugin, version_id: UUID, db_session: Session
) -> PluginVersion:
    version = db_session.scalars(
        select(PluginVersion)
        .where(PluginVersion.id == version_id, PluginVersion.plugin_id == plugin.id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if version is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill version not found.")
    if version.review_status != PluginReviewStatus.PENDING:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "This version has no pending publish request."
        )
    return version


def version_to_approve(
    plugin: Plugin, version_id: UUID, db_session: Session
) -> PluginVersion:
    """The pending version, when it is newer than the published version."""
    version = pending_version(plugin, version_id, db_session)
    published_number = db_session.scalar(
        select(PluginVersion.version_number).where(
            PluginVersion.id == plugin.published_version_id
        )
    )
    if published_number is not None and version.version_number <= published_number:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Only a version newer than the published version can be approved.",
        )
    return version


def deny_review__no_commit(
    plugin: Plugin, version_id: UUID, db_session: Session
) -> None:
    pending_version(
        plugin, version_id, db_session
    ).review_status = PluginReviewStatus.DENIED
    db_session.flush()


@dataclass(frozen=True)
class PluginReviewRequest:
    plugin_id: UUID
    # Name in the frontmatter of the pending version.
    name: str | None
    version_id: UUID
    version_number: int
    # None for a first publish.
    published_version_number: int | None
    requested_by_user_id: UUID | None
    requested_by_email: str | None
    requested_at: datetime | None


def list_review_requests(db_session: Session) -> list[PluginReviewRequest]:
    """Every pending version, oldest request first."""
    published: type[PluginVersion] = aliased(PluginVersion)
    rows = db_session.execute(
        select(
            PluginVersion.plugin_id,
            skill_name_in_version(PluginVersion.id.expression),
            PluginVersion.id,
            PluginVersion.version_number,
            published.version_number,
            PluginVersion.review_requested_by_user_id,
            User.__table__.c.email,
            PluginVersion.review_requested_at,
        )
        .join(Plugin, Plugin.id == PluginVersion.plugin_id)
        .outerjoin(published, published.id == Plugin.published_version_id)
        .outerjoin(
            User.__table__,
            User.__table__.c.id == PluginVersion.review_requested_by_user_id,
        )
        .where(PluginVersion.review_status == PluginReviewStatus.PENDING)
        .order_by(PluginVersion.review_requested_at, PluginVersion.id)
    ).all()
    return [
        PluginReviewRequest(
            plugin_id=row[0],
            name=row[1],
            version_id=row[2],
            version_number=row[3],
            published_version_number=row[4],
            requested_by_user_id=row[5],
            requested_by_email=row[6],
            requested_at=row[7],
        )
        for row in rows
    ]
