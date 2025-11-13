import csv
import io
from datetime import datetime, timezone
from http import HTTPStatus
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ee.onyx.db.query_history import (
    fetch_chat_sessions_eagerly_by_time,
    get_page_of_chat_sessions,
    get_total_filtered_chat_sessions_count,
)
from ee.onyx.server.query_history.models import (
    ChatSessionMinimal,
    ChatSessionSnapshot,
    MessageSnapshot,
    QuestionAnswerPairSnapshot,
)
from onyx.auth.users import current_admin_user, get_display_email
from onyx.chat.chat_utils import create_chat_chain
from onyx.configs.app_configs import ONYX_QUERY_HISTORY_TYPE
from onyx.configs.constants import (
    MessageType,
    QAFeedbackType,
    QueryHistoryType,
    SessionType,
)
from onyx.db.chat import get_chat_session_by_id, get_chat_sessions_by_user
from onyx.db.engine import get_session
from onyx.db.models import ChatSession, User
from onyx.server.documents.models import PaginatedReturn
from onyx.server.query_and_chat.models import ChatSessionDetails, ChatSessionsResponse

router = APIRouter(tags=["История запросов"])

ONYX_ANONYMIZED_EMAIL = "anonymous@anonymous.invalid"


def _get_valid_snapshots(
    chat_session_snapshots: list,
    feedback_type: QAFeedbackType | None,
):
    """Фильтрует список снимков чат-сессий, оставляя только
    валидные и соответствующие типу фидбека.

    Args:
        chat_session_snapshots: Список снимков чат-сессий (может содержать None)
        feedback_type: Тип фидбека для фильтрации (лайк/дизлайк).
                        Если None - фильтрация не применяется.

    Returns:
        Отфильтрованный список валидных снимков сессий
    """

    # Отфильтровываем None значения
    valid_snapshots = []
    for snapshot in chat_session_snapshots:
        if snapshot is not None:
            valid_snapshots.append(snapshot)

    # Дополнительная фильтрация по типу фидбека
    if feedback_type:
        filtered_snapshots = []

        for valid_snapshot in valid_snapshots:
            has_feedback = False

            # Проверяем каждое сообщение в сессии на наличие нужного типа фидбека
            for message in valid_snapshot.messages:
                if message.feedback_type == feedback_type:
                    has_feedback = True
                    break

            if has_feedback:
                filtered_snapshots.append(valid_snapshot)

        valid_snapshots = filtered_snapshots

    return valid_snapshots


def _fetch_and_process_chat_session_history(
    db_session: Session,
    start: datetime,
    end: datetime,
    feedback_type: QAFeedbackType | None,
    limit: int | None = 500,
) -> list[ChatSessionSnapshot]:
    """Получает и обрабатывает историю чат-сессий за указанный период.

    Выполняет два основных этапа:
        1. Загрузка сессий из БД с жадной загрузкой связанных данных
        2. Создание снимков сессий с фильтрацией по валидности и типу фидбека

    Args:
        db_session: Сессия базы данных
        start: Начало временного диапазона
        end: Конец временного диапазона
        feedback_type: Тип фидбека для фильтрации (опционально)
        limit: Ограничение количества сессий (по умолчанию 500)

    Returns:
        Список обработанных снимков чат-сессий
    """

    # Загрузка сессий из БД с сортировкой по времени
    chat_sessions = fetch_chat_sessions_eagerly_by_time(
        start=start,
        end=end,
        db_session=db_session,
        limit=limit,
    )

    # Создание снимков для каждой сессии (медленная операция, необходима оптимизация)
    chat_session_snapshots = [
        _snapshot_from_chat_session(chat_session=chat_session, db_session=db_session)
        for chat_session in chat_sessions
    ]

    # Фильтрация снимков по валидности и типу фидбека
    valid_snapshots = _get_valid_snapshots(
        chat_session_snapshots=chat_session_snapshots,
        feedback_type=feedback_type,
    )

    return valid_snapshots


def _get_chat_session_snapshot(
    chat_session: ChatSession,
    all_messages: list,
    flow_type: SessionType,
) -> ChatSessionSnapshot:
    """Создает финальный снимок чат-сессии из сырых данных.

    Выполняет подготовку данных для отображения:
        - Обработка email пользователя (с возможной анонимизацией)
        - Фильтрация системных сообщений
        - Формирование структурированного снимка сессии

    Args:
        chat_session: Модель чат-сессии из БД
        all_messages: Все сообщения сессии (включая системные)
        flow_type: Тип сессии

    Returns:
        Структурированный снимок чат-сессии для отображения
    """

    # Обработка email пользователя
    if chat_session.user:
        email = chat_session.user.email
    else:
        email = None
    user_email = get_display_email(email=email)

    # Фильтрация системных сообщений
    filtered_messages = []
    for message in all_messages:
        if message.message_type != MessageType.SYSTEM:
            building_message_snapshot = MessageSnapshot.build(message)
            filtered_messages.append(building_message_snapshot)

    # Обработка названия ассистента
    if chat_session.persona:
        assistant_name = chat_session.persona.name
    else:
        assistant_name = None

    # Создание финального снимка сессии
    chat_session_snapshot = ChatSessionSnapshot(
        id=chat_session.id,
        user_email=user_email,
        name=chat_session.description,
        messages=filtered_messages,
        assistant_id=chat_session.persona_id,
        assistant_name=assistant_name,
        time_created=chat_session.time_created,
        flow_type=flow_type,
    )

    return chat_session_snapshot


def _snapshot_from_chat_session(
    chat_session: ChatSession,
    db_session: Session,
) -> ChatSessionSnapshot | None:
    """Создает полный снимок чат-сессии
    с восстановлением цепочки сообщений.

    Восстанавливает линейную цепочку сообщений сессии и создает снимок
    для отображения. Обрабатывает ошибки в структуре старых сессий.

    Args:
        chat_session: Модель чат-сессии из БД
        db_session: Сессия базы данных

    Returns:
        Снимок сессии или None если сессия имеет некорректную структуру
    """
    try:
        # Восстановление цепочки сообщений (может падать на старых сессиях)
        last_message, all_messages = create_chat_chain(
            chat_session_id=chat_session.id,
            db_session=db_session
        )
        all_messages.append(last_message)
    except RuntimeError:
        return None

    # Определение типа сессии
    if chat_session.onyxbot_flow:
        flow_type = SessionType.SLACK
    else:
        flow_type = SessionType.CHAT

    # Создание финального снимка
    chat_session_snapshot = _get_chat_session_snapshot(
        chat_session=chat_session,
        all_messages=all_messages,
        flow_type=flow_type,
    )

    return chat_session_snapshot


@router.get("/admin/chat-sessions")
def get_user_chat_sessions(
    user_id: UUID,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionsResponse:
    # we specifically don't allow this endpoint if "anonymized" since
    # this is a direct query on the user id
    if ONYX_QUERY_HISTORY_TYPE in [
        QueryHistoryType.DISABLED,
        QueryHistoryType.ANONYMIZED,
    ]:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Per user query history has been disabled by the administrator.",
        )

    try:
        chat_sessions = get_chat_sessions_by_user(
            user_id=user_id, deleted=False, db_session=db_session, limit=0
        )

    except ValueError:
        raise ValueError("Chat session does not exist or has been deleted")

    return ChatSessionsResponse(
        sessions=[
            ChatSessionDetails(
                id=chat.id,
                name=chat.description,
                persona_id=chat.persona_id,
                time_created=chat.time_created.isoformat(),
                time_updated=chat.time_updated.isoformat(),
                shared_status=chat.shared_status,
                folder_id=chat.folder_id,
                current_alternate_model=chat.current_alternate_model,
            )
            for chat in chat_sessions
        ]
    )


@router.get("/admin/chat-session-history")
def get_chat_session_history(
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1),
    feedback_type: QAFeedbackType | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[ChatSessionMinimal]:
    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.DISABLED:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )

    page_of_chat_sessions = get_page_of_chat_sessions(
        page_num=page_num,
        page_size=page_size,
        db_session=db_session,
        start_time=start_time,
        end_time=end_time,
        feedback_filter=feedback_type,
    )

    total_filtered_chat_sessions_count = get_total_filtered_chat_sessions_count(
        db_session=db_session,
        start_time=start_time,
        end_time=end_time,
        feedback_filter=feedback_type,
    )

    minimal_chat_sessions: list[ChatSessionMinimal] = []

    for chat_session in page_of_chat_sessions:
        minimal_chat_session = ChatSessionMinimal.from_chat_session(chat_session)
        if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
            minimal_chat_session.user_email = ONYX_ANONYMIZED_EMAIL
        minimal_chat_sessions.append(minimal_chat_session)

    return PaginatedReturn(
        items=minimal_chat_sessions,
        total_items=total_filtered_chat_sessions_count,
    )


@router.get("/admin/chat-session-history/{chat_session_id}")
def get_chat_session_admin(
    chat_session_id: UUID,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionSnapshot:
    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.DISABLED:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )

    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_session_id,
            user_id=None,  # view chat regardless of user
            db_session=db_session,
            include_deleted=True,
        )
    except ValueError:
        raise HTTPException(
            400, f"Chat session with id '{chat_session_id}' does not exist."
        )
    snapshot = _snapshot_from_chat_session(
        chat_session=chat_session, db_session=db_session
    )

    if snapshot is None:
        raise HTTPException(
            400,
            f"Could not create snapshot for chat session with id '{chat_session_id}'",
        )

    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
        snapshot.user_email = ONYX_ANONYMIZED_EMAIL

    return snapshot


@router.get("/admin/query-history-csv")
def get_query_history_as_csv(
    _: User | None = Depends(current_admin_user),
    start: datetime | None = None,
    end: datetime | None = None,
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.DISABLED:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )

    # this call is very expensive and is timing out via endpoint
    # TODO: optimize call and/or generate via background task
    complete_chat_session_history = _fetch_and_process_chat_session_history(
        db_session=db_session,
        start=start or datetime.fromtimestamp(0, tz=timezone.utc),
        end=end or datetime.now(tz=timezone.utc),
        feedback_type=None,
        limit=None,
    )

    question_answer_pairs: list[QuestionAnswerPairSnapshot] = []
    for chat_session_snapshot in complete_chat_session_history:
        if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
            chat_session_snapshot.user_email = ONYX_ANONYMIZED_EMAIL

        question_answer_pairs.extend(
            QuestionAnswerPairSnapshot.from_chat_session_snapshot(chat_session_snapshot)
        )

    # Create an in-memory text stream
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream, fieldnames=list(QuestionAnswerPairSnapshot.model_fields.keys())
    )
    writer.writeheader()
    for row in question_answer_pairs:
        writer.writerow(row.to_json())

    # Reset the stream's position to the start
    stream.seek(0)

    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment;filename=onyx_query_history.csv"},
    )
