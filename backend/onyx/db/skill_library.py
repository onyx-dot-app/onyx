from collections.abc import Collection
from uuid import UUID

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session

from onyx.db.models import Marketplace, Skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from shared_configs.contextvars import get_current_tenant_id


def skill_library_owner() -> ColumnElement[UUID | None]:
    """Library identity; the caller must outer-join Marketplace."""
    return case(
        (Skill.marketplace_id.is_not(None), Marketplace.owner_user_id),
        (Skill.public_permission.is_not(None), None),
        else_=Skill.author_user_id,
    )


def lock_skill_library_names(
    owner_id: UUID | None, names: Collection[str], db_session: Session
) -> None:
    """Take membership and marketplace locks first, and skill row locks afterwards."""
    library = str(owner_id) if owner_id is not None else "company"
    tenant_id = get_current_tenant_id()
    for name in sorted(set(names)):
        db_session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(
                        tenant_id + ":skill-library:" + library + ":" + name,
                        0,
                    )
                )
            )
        )


def assert_new_skill_name_available(
    owner_id: UUID | None, name: str, db_session: Session
) -> None:
    lock_skill_library_names(owner_id, [name], db_session)
    if (
        db_session.scalar(
            select(Skill.id)
            .outerjoin(Marketplace, Skill.marketplace_id == Marketplace.id)
            .where(
                Skill.name == name,
                Skill.retired_at.is_(None),
                skill_library_owner().is_not_distinct_from(owner_id),
            )
            .limit(1)
        )
        is not None
    ):
        raise OnyxError(
            OnyxErrorCode.SKILL_NAME_CONFLICT,
            f"A live skill named '{name}' already exists in this library. Upload a new version instead.",
        )
