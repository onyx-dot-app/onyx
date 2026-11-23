"""Auto-naming of chat sessions.

A new chat is named from its first question while the answer streams
(`name_new_chat_session`, started by `chat/execution.py:start_chat_turn`).
`PUT /chat/rename-chat-session` with no name (`name_chat_session`) names a chat
that still has none. One cache lock per chat keeps the two from generating a
name twice, and both save only while the chat is unnamed, so a rename wins.

Without an admin-set chat-naming model, the chat's own model names it: the
model the turn runs on, or for a naming request, the model the chat's agent and
saved override select.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.chat.chat_utils import convert_chat_history_basic
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    create_chat_history_chain,
    get_chat_session_by_id,
    save_chat_session_name_if_unnamed,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import LLMModelFlowType, record_mode_persists_content
from onyx.db.models import ChatMessage, User
from onyx.llm.factory import (
    get_default_utility_llm,
    get_llm_for_persona,
    get_llm_token_counter,
)
from onyx.llm.interfaces import LLM
from onyx.secondary_llm_flows.chat_session_naming import (
    generate_chat_session_name,
    get_fallback_chat_session_name,
)
from onyx.server.query_and_chat.token_limit import (
    check_model_spend_limits,
    check_token_rate_limits,
)
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.tracing.framework.create import ChatTraceMetadata, ensure_trace
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_MAX_TOKENS_FOR_NAMING = 3000
# Generating a name takes seconds; the lock outlives it if its holder dies.
_NAMING_LOCK_SECONDS = 60
# How long a naming request waits for a name the chat turn is generating.
_NAMING_WAIT_SECONDS = 30


@contextmanager
def _naming_lock(chat_session_id: UUID, *, wait_seconds: float) -> Iterator[bool]:
    """Hold the chat's naming lock. Yields False only when another naming holds
    it. A cache failure yields True without the lock: the conditional save
    still keeps a rename, and naming must not fail on the cache."""
    lock: CacheLock | None = None
    acquired = False
    try:
        lock = get_cache_backend().lock(
            f"chat_session_naming:{chat_session_id}", timeout=_NAMING_LOCK_SECONDS
        )
        acquired = (
            lock.acquire(blocking=True, blocking_timeout=wait_seconds)
            if wait_seconds > 0
            else lock.acquire(blocking=False)
        )
        may_proceed = acquired or wait_seconds > 0
    except Exception:
        logger.warning("Chat naming lock unavailable; naming without it")
        may_proceed = True
    try:
        yield may_proceed
    finally:
        if acquired and lock is not None:
            try:
                if lock.owned():
                    lock.release()
            except Exception:
                # The lock expires on its own; the name is already saved.
                logger.warning("Could not release the chat naming lock")


def generate_chat_session_name_or_fallback(
    *,
    chat_history: list[ChatMessage],
    user: User,
    chat_session_id: UUID,
    get_chat_llm: Callable[[], LLM],
    additional_headers: dict[str, str] | None,
) -> str:
    """Generate a name from `chat_history`, or fall back to the first question
    when generation is not allowed or fails. `get_chat_llm` gives the chat's
    model; it is called only when no chat-naming model is set."""
    user_id = user.id
    fallback_name = get_fallback_chat_session_name(chat_history)

    try:
        check_token_rate_limits(user)
        llm = get_default_utility_llm(
            additional_headers=additional_headers,
            flow_type=LLMModelFlowType.CHAT_NAMING,
        )
        if llm is None:
            llm = get_chat_llm()
            with get_session_with_current_tenant() as db_session:
                check_llm_cost_limit_for_provider(
                    db_session=db_session,
                    tenant_id=get_current_tenant_id(),
                    llm_provider_api_key=llm.config.api_key,
                )
            check_model_spend_limits(user, llm.config.model_configuration_id)

        token_counter = get_llm_token_counter(llm)
        simple_chat_history = convert_chat_history_basic(
            chat_history=chat_history,
            token_counter=token_counter,
            max_individual_message_tokens=_MAX_TOKENS_FOR_NAMING,
            max_total_tokens=_MAX_TOKENS_FOR_NAMING,
        )
        with ensure_trace(
            "chat_session_naming",
            group_id=str(chat_session_id),
            metadata=ChatTraceMetadata(
                chat_session_id=str(chat_session_id),
                user_id=str(user_id) if user_id else None,
            ).model_dump(),
        ):
            return generate_chat_session_name(
                chat_history=simple_chat_history,
                llm=llm,
            )
    except Exception as error:
        logger.warning("Failed to generate chat session name: %s", error)
        return fallback_name


def name_new_chat_session(
    *,
    chat_session_id: UUID,
    user: User,
    chat_llm: LLM,
    additional_headers: dict[str, str] | None,
) -> str | None:
    """Name a chat from its first question and save the name. `chat_llm` is
    the model the turn runs on (its first model when it compares several).

    Returns the saved name, or None when the chat keeps no content, already
    has a name, got one while this one was generated, or is being named by a
    naming request.
    """
    with _naming_lock(chat_session_id, wait_seconds=0) as may_proceed:
        # A naming request already holds it and names the chat.
        if not may_proceed:
            return None
        with get_session_with_current_tenant() as db_session:
            chat_session = get_chat_session_by_id(
                chat_session_id=chat_session_id,
                user_id=user.id,
                db_session=db_session,
            )
            if chat_session.description or not record_mode_persists_content(
                chat_session.incognito_record_mode
            ):
                return None
            first_question = [
                message
                for message in create_chat_history_chain(
                    chat_session_id=chat_session_id,
                    db_session=db_session,
                )
                if message.message_type == MessageType.USER
            ][:1]
        if not first_question:
            return None

        name = generate_chat_session_name_or_fallback(
            chat_history=first_question,
            user=user,
            chat_session_id=chat_session_id,
            get_chat_llm=lambda: chat_llm,
            additional_headers=additional_headers,
        )
        with get_session_with_current_tenant() as db_session:
            saved = save_chat_session_name_if_unnamed(
                db_session=db_session,
                user_id=user.id,
                chat_session_id=chat_session_id,
                name=name,
            )
        return name if saved else None


def name_chat_session(
    *,
    chat_session_id: UUID,
    user: User,
    additional_headers: dict[str, str] | None,
) -> str:
    """Name a chat from its whole history unless it has a name, and return
    the chat's name. A name the chat turn is still generating is awaited and
    returned, not generated a second time."""
    with _naming_lock(chat_session_id, wait_seconds=_NAMING_WAIT_SECONDS):
        with get_session_with_current_tenant() as db_session:
            chat_session = get_chat_session_by_id(
                chat_session_id=chat_session_id,
                user_id=user.id,
                db_session=db_session,
                eager_load_persona=True,
            )
            if chat_session.description:
                return chat_session.description
            chat_history = create_chat_history_chain(
                chat_session_id=chat_session_id,
                db_session=db_session,
            )
            persona = chat_session.persona
            llm_override = chat_session.llm_override

        name = generate_chat_session_name_or_fallback(
            chat_history=chat_history,
            user=user,
            chat_session_id=chat_session_id,
            get_chat_llm=partial(
                get_llm_for_persona,
                persona=persona,
                user=user,
                llm_override=llm_override,
                additional_headers=additional_headers,
            ),
            additional_headers=additional_headers,
        )
        with get_session_with_current_tenant() as db_session:
            if save_chat_session_name_if_unnamed(
                db_session=db_session,
                user_id=user.id,
                chat_session_id=chat_session_id,
                name=name,
            ):
                return name
            # Renamed while this name was generated: the rename stands.
            return (
                get_chat_session_by_id(
                    chat_session_id=chat_session_id,
                    user_id=user.id,
                    db_session=db_session,
                ).description
                or name
            )
