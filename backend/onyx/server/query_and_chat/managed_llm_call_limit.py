from datetime import datetime
from datetime import timedelta
from datetime import timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.db.chat import get_chat_session_by_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import can_user_access_llm_provider
from onyx.db.llm import fetch_default_provider_model
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import fetch_user_group_ids
from onyx.db.llm_call_limit import fetch_managed_llm_call_limit
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.query_and_chat.models import CreateChatMessageRequest


_LIMIT_KEY_PREFIX = "managed_llm_calls"


def _seconds_until_utc_midnight(now: datetime | None = None) -> int:
    if now is None:
        now = datetime.now(timezone.utc)
    next_midnight = datetime(
        year=now.year,
        month=now.month,
        day=now.day,
        tzinfo=timezone.utc,
    ) + timedelta(days=1)
    return max(int((next_midnight - now).total_seconds()), 1)


def _resolve_llm_provider_for_chat_request(
    chat_message_req: CreateChatMessageRequest,
    user: User | None,
    db_session: Session,
) -> LLMProviderModel | None:
    user_id = user.id if user is not None else None
    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_message_req.chat_session_id,
            user_id=user_id,
            db_session=db_session,
        )
    except ValueError:
        return None

    persona = chat_session.persona
    llm_override = chat_message_req.llm_override or chat_session.llm_override
    provider_name = llm_override.model_provider if llm_override else None
    if not provider_name:
        provider_name = persona.llm_model_provider_override

    if not provider_name:
        return fetch_default_provider_model(db_session)

    provider_model = fetch_existing_llm_provider(provider_name, db_session)
    if not provider_model:
        return None

    user_group_ids = fetch_user_group_ids(db_session, user)
    if not can_user_access_llm_provider(
        provider_model, user_group_ids, persona=persona
    ):
        return fetch_default_provider_model(db_session)

    return provider_model


def enforce_managed_llm_call_limit(
    chat_message_req: CreateChatMessageRequest,
    user: User | None,
) -> None:
    with get_session_with_current_tenant() as db_session:
        limit = fetch_managed_llm_call_limit(db_session, enabled_only=True)
        if not limit:
            return

        provider_model = _resolve_llm_provider_for_chat_request(
            chat_message_req=chat_message_req,
            user=user,
            db_session=db_session,
        )
        if not provider_model or not provider_model.is_onyx_managed:
            return
        daily_call_limit = limit.daily_call_limit

    redis_client = get_redis_client()
    today = datetime.now(timezone.utc).date().isoformat()
    key = f"{_LIMIT_KEY_PREFIX}:{today}"
    count = redis_client.incr(key)
    if count == 1:
        redis_client.expire(key, _seconds_until_utc_midnight())

    if count > daily_call_limit:
        raise HTTPException(
            status_code=429,
            detail="Daily managed LLM call limit exceeded for organization.",
        )
