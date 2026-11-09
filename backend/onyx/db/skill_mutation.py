from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Marketplace, Skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def assert_skill_mutable(skill: Skill) -> None:
    if skill.retired_at is not None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "retired")


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
