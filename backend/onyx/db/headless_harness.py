"""Read-only identity and corpus checks for the trusted host experiment runner."""

from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.sql.elements import KeyedColumnElement

from onyx.auth.permissions import has_global_permission
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.db.users import fetch_user_by_id


def prepare_headless_user(user_id: str | None) -> tuple[User, dict]:
    SqlEngine.init_engine(pool_size=5, max_overflow=5)
    with get_session_with_current_tenant() as session:
        database = session.execute(text("SELECT current_database()")).scalar_one()
        settings = get_current_search_settings(session)
        if (
            database != "craft_corpus_v2_20260908"
            or settings.index_name != "danswer_corpus_v2_20260908"
        ):
            raise ValueError(
                "Headless runner requires the isolated craft benchmark corpus"
            )
        if user_id is None:
            user_id_col: KeyedColumnElement[Any] = User.__table__.c.id
            is_active_col: KeyedColumnElement[Any] = User.__table__.c.is_active
            ids = list(
                session.scalars(select(user_id_col).where(is_active_col.is_(True)))
            )
            if len(ids) != 1:
                raise ValueError(
                    "Specify --user-id: benchmark does not have exactly one active user"
                )
            selected_id = ids[0]
        else:
            selected_id = UUID(user_id)
        user = fetch_user_by_id(session, selected_id)
        if user is None or not user.is_active:
            raise ValueError("Selected benchmark user is missing or inactive")
        for permission in (Permission.READ_SEARCH, Permission.WRITE_CHAT):
            if not has_global_permission(user, permission):
                raise ValueError("Selected user lacks search/chat permission")
        identity = {
            "database": database,
            "index": settings.index_name,
            "search_settings_id": settings.id,
            "user_id": str(user.id),
        }
        session.expunge(user)
    return user, identity
