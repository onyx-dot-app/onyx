from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import TemporaryUserCheatSheetContext

# EXPLORATION TESTING


def get_user_cheat_sheet_context(db_session: Session) -> dict[str, Any] | None:
    stmt = select(TemporaryUserCheatSheetContext).order_by(
        TemporaryUserCheatSheetContext.created_at.desc()
    )
    result = db_session.execute(stmt).scalar_one_or_none()
    return result.context if result else None


def update_user_cheat_sheet_context(
    db_session: Session, new_cheat_sheet_context: dict[str, Any]
) -> None:
    stmt = select(TemporaryUserCheatSheetContext).order_by(
        TemporaryUserCheatSheetContext.created_at.desc()
    )
    result = db_session.execute(stmt).scalar_one_or_none()
    if result:
        result.context = new_cheat_sheet_context
        db_session.commit()
    else:
        new_context = TemporaryUserCheatSheetContext(context=new_cheat_sheet_context)
        db_session.add(new_context)
        db_session.commit()
