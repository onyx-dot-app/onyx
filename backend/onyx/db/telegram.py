import string
import secrets

from uuid import UUID

from sqlalchemy import select, update, exists
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.models import TelegramUserApiKey, TelegramUserSettings, User


def get_user_telegram_api_key_by_user_id(user_id: UUID, db_session: Session) -> TelegramUserApiKey | None:
    stmt = select(TelegramUserApiKey).where(TelegramUserApiKey.user_id == user_id)

    api_key = db_session.execute(stmt).scalars().first()

    return api_key

def get_user_by_telegram_api_key(token: str, db_session: Session) -> User | None:
    stmt = select(TelegramUserApiKey).where(TelegramUserApiKey.api_key == token)

    result = db_session.execute(stmt).scalars().first()

    if not result:
        return None

    stmt = select(User).where(User.id == result.user_id)

    return db_session.execute(stmt).scalars().first()


def get_user_by_telegram_user_id(user_id: int, db_session: Session) -> User | None:
    stmt = select(TelegramUserApiKey).where(TelegramUserApiKey.user_id == user_id)

    result = db_session.execute(stmt).scalars().first()

    if not result:
        return None

    stmt = select(User).where(User.id == result.user_id)

    return db_session.execute(stmt).scalars().first()


def add_user_telegram_api_key(user_id: UUID, db_session: Session):
    chars = string.ascii_letters + string.digits
    api_key = ''.join(secrets.choice(chars) for _ in range(15))
    stmt = insert(TelegramUserApiKey).values(user_id=user_id, api_key=api_key).returning(TelegramUserApiKey)
    on_conflict_stmt = stmt.on_conflict_do_nothing()
    result = db_session.scalars(on_conflict_stmt)
    db_session.commit()

    return result.first()


def edit_telegram_user_id_by_api_key(api_key: str, user_id: int, db_session: Session):
    stmt = update(TelegramUserApiKey).where(TelegramUserApiKey.api_key == api_key).values(telegram_user_id=user_id)

    db_session.execute(stmt)
    db_session.commit()


def get_user_telegram_api_key_by_tg_user_id(user_id: int, db_session: Session) -> TelegramUserApiKey | None:
    stmt = select(TelegramUserApiKey).where(TelegramUserApiKey.telegram_user_id == user_id)

    api_key = db_session.execute(stmt).scalars().first()

    return api_key


def check_api_token(api_key: str, db_session: Session) -> bool:
    stmt = exists(TelegramUserApiKey).where(TelegramUserApiKey.api_key == api_key)

    result = db_session.query(stmt).scalar()

    return result


def get_user_telegram_settings(user_id: int, db_session: Session) -> TelegramUserSettings | None:
    stmt = select(TelegramUserSettings).where(TelegramUserSettings.user_id == user_id)

    result = db_session.scalars(stmt)
    if result:
        return result.first()


def init_user_telegram_settings(user_id: int, db_session: Session):
    stmt = insert(TelegramUserSettings).values(user_id=user_id)

    db_session.execute(stmt)

    db_session.commit()


def edit_user_telegram_settings_model(user_id: int, model: dict, db_session: Session):
    stmt = update(TelegramUserSettings).where(TelegramUserSettings.user_id == user_id).values(model=model)

    db_session.execute(stmt)

    db_session.commit()


def edit_user_telegram_settings_persona(user_id: int, persona_id: int, prompt_id: int, db_session: Session):
    stmt = update(TelegramUserSettings).where(TelegramUserSettings.user_id == user_id).values(persona_id=persona_id,
                                                                                              prompt_id=prompt_id)

    db_session.execute(stmt)

    db_session.commit()
