from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Marketplace, Skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def assert_skill_mutable(skill: Skill) -> None:
    if skill.retired_at is not None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "retired")


def assert_skill_content_editable(skill: Skill) -> None:
    assert_skill_mutable(skill)
    if skill.marketplace_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Change synced skill content in GitHub."
        )


def assert_skill_deletable(skill: Skill) -> None:
    if skill.marketplace_id is not None and skill.retired_at is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Remove active synced skills from GitHub."
        )


def is_company_marketplace_skill(skill: Skill, db_session: Session) -> bool:
    return (
        skill.marketplace_id is not None
        and db_session.scalar(
            select(Marketplace.id).where(
                Marketplace.id == skill.marketplace_id,
                Marketplace.owner_user_id.is_(None),
            )
        )
        is not None
    )
