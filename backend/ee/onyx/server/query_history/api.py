import csv
import io
import re
import uuid
from collections.abc import Generator
from collections.abc import Iterable
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ee.onyx.background.task_name_builders import query_history_task_name
from ee.onyx.db.query_history import get_all_query_history_export_tasks
from ee.onyx.db.query_history import get_lti_project_daily_query_history_aggregates
from ee.onyx.db.query_history import get_lti_project_feedback_aggregate
from ee.onyx.db.query_history import get_lti_project_user_messages_for_theme_analysis
from ee.onyx.db.query_history import get_page_of_chat_sessions
from ee.onyx.db.query_history import get_total_filtered_chat_sessions_count
from ee.onyx.server.query_history.models import ChatSessionMinimal
from ee.onyx.server.query_history.models import ChatSessionSnapshot
from ee.onyx.server.query_history.models import LtiInstructorDailyTrend
from ee.onyx.server.query_history.models import LtiInstructorThemeAnalysis
from ee.onyx.server.query_history.models import LtiInstructorTrendsResponse
from ee.onyx.server.query_history.models import MessageSnapshot
from ee.onyx.server.query_history.models import QueryHistoryExport
from ee.onyx.server.query_history.models import QuestionAnswerPairSnapshot
from onyx.auth.permissions import require_permission
from onyx.auth.schemas import UserRole
from onyx.auth.users import current_user
from onyx.auth.users import get_display_email
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.background.task_utils import construct_query_history_report_name
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.chat.chat_utils import create_chat_history_chain
from onyx.configs.app_configs import ONYX_QUERY_HISTORY_TYPE
from onyx.configs.constants import CELERY_QUERY_HISTORY_EXPORT_TASK_EXPIRES
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import FileType
from onyx.configs.constants import MessageType
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.configs.constants import QAFeedbackType
from onyx.configs.constants import QueryHistoryType
from onyx.configs.constants import SessionType
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_chat_sessions_by_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.enums import TaskStatus
from onyx.db.file_record import get_query_history_export_files
from onyx.db.lti import get_lti_course_project_for_user
from onyx.db.models import ChatSession
from onyx.db.models import User
from onyx.db.tasks import get_task_with_id
from onyx.db.tasks import register_task
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.factory import get_default_llm
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.llm.utils import llm_response_to_string
from onyx.server.documents.models import PaginatedReturn
from onyx.server.query_and_chat.models import ChatSessionDetails
from onyx.server.query_and_chat.models import ChatSessionsResponse
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import parse_llm_json_response
from onyx.utils.threadpool_concurrency import parallel_yield
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()
logger = setup_logger()

ONYX_ANONYMIZED_EMAIL = "anonymous@anonymous.invalid"
LTI_INSTRUCTOR_THEME_CACHE_TTL_SECONDS = 60 * 60
LTI_INSTRUCTOR_THEME_MESSAGE_LIMIT = 200
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)

# Column order for query-history CSV exports. Shared by the admin Celery export
# task and the synchronous LTI instructor export so both produce byte-identical files.
QUERY_HISTORY_CSV_FIELDS = list(QuestionAnswerPairSnapshot.model_fields.keys())


def ensure_query_history_is_enabled(
    disallowed: list[QueryHistoryType],
) -> None:
    if ONYX_QUERY_HISTORY_TYPE in disallowed:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Query history has been disabled by the administrator.",
        )


def _ensure_lti_instructor_project_access(
    project_id: int,
    user: User,
    db_session: Session,
) -> None:
    if user.role not in {UserRole.CURATOR, UserRole.ADMIN}:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only Canvas course instructors can access this query history.",
        )

    project = get_lti_course_project_for_user(
        project_id=project_id,
        user_id=user.id,
        db_session=db_session,
    )
    if project is None:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "User does not manage this Canvas course project.",
        )


def _ensure_valid_time_range(start: datetime, end: datetime) -> None:
    if start >= end:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Start time must come before end time.",
        )


def _redact_student_identifiers(text: str | None) -> str | None:
    if text is None:
        return None
    return _EMAIL_RE.sub("[redacted email]", text)


def _force_anonymized_minimal_session(
    chat_session: ChatSessionMinimal,
    redact_content: bool = False,
) -> ChatSessionMinimal:
    chat_session.user_email = ONYX_ANONYMIZED_EMAIL
    if redact_content:
        chat_session.name = _redact_student_identifiers(chat_session.name)
        chat_session.first_user_message = (
            _redact_student_identifiers(chat_session.first_user_message) or ""
        )
        chat_session.first_ai_message = (
            _redact_student_identifiers(chat_session.first_ai_message) or ""
        )
    return chat_session


def _force_anonymized_snapshot(
    snapshot: ChatSessionSnapshot,
    redact_content: bool = False,
) -> ChatSessionSnapshot:
    snapshot.user_email = ONYX_ANONYMIZED_EMAIL
    if redact_content:
        snapshot.name = _redact_student_identifiers(snapshot.name)
        for message in snapshot.messages:
            message.message = _redact_student_identifiers(message.message) or ""
            message.feedback_text = _redact_student_identifiers(message.feedback_text)
    return snapshot


def _theme_cache_key(project_id: int, start: datetime, end: datetime) -> str:
    return (
        "lti:instructor:query-history:themes:"
        f"{project_id}:{start.isoformat()}:{end.isoformat()}"
    )


def _get_cached_theme_analysis(
    project_id: int,
    start: datetime,
    end: datetime,
) -> LtiInstructorThemeAnalysis | None:
    try:
        cached = get_cache_backend().get(_theme_cache_key(project_id, start, end))
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning("Could not read cached LTI instructor themes: %s", e)
        return None

    if cached is None:
        return None

    cached_str = cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
    try:
        return LtiInstructorThemeAnalysis.model_validate_json(cached_str)
    except ValueError as e:
        logger.warning("Could not parse cached LTI instructor themes: %s", e)
        return None


def _set_cached_theme_analysis(
    project_id: int,
    start: datetime,
    end: datetime,
    analysis: LtiInstructorThemeAnalysis,
) -> None:
    try:
        get_cache_backend().set(
            _theme_cache_key(project_id, start, end),
            analysis.model_dump_json(),
            ex=LTI_INSTRUCTOR_THEME_CACHE_TTL_SECONDS,
        )
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning("Could not cache LTI instructor themes: %s", e)


def _generate_theme_analysis(
    questions: list[str],
) -> LtiInstructorThemeAnalysis:
    if not questions:
        return LtiInstructorThemeAnalysis()

    redacted_questions = [
        _redact_student_identifiers(question) or "" for question in questions
    ]
    numbered_questions = "\n".join(
        f"{index + 1}. {question[:500]}"
        for index, question in enumerate(redacted_questions)
    )

    system_prompt = SystemMessage(
        content=(
            "You summarize anonymized student tutor questions for an instructor. "
            "Do not infer or expose student identity. Return only JSON with this "
            'shape: {"summary": string|null, "clusters": [{"label": string, '
            '"summary": string, "count": integer, "friction_score": integer, '
            '"representative_question": string|null}]}. Keep labels short.'
        )
    )
    user_prompt = UserMessage(
        content=(
            "Cluster these student questions into at most 6 themes. "
            "Use higher friction_score values for themes with repeated confusion "
            "or negative-feedback wording.\n\n"
            f"{numbered_questions}"
        )
    )

    try:
        llm = get_default_llm()
        with llm_generation_span(
            llm=llm,
            flow="lti_instructor_theme_analysis",
            input_messages=[system_prompt, user_prompt],
        ) as span_generation:
            response = llm.invoke(
                prompt=[system_prompt, user_prompt],
                reasoning_effort=ReasoningEffort.OFF,
                max_tokens=1200,
                structured_response_format={"type": "json_object"},
            )
            record_llm_response(span_generation, response)

        parsed_response = parse_llm_json_response(llm_response_to_string(response))
        if parsed_response is None:
            logger.warning("LTI instructor theme analysis returned non-JSON output")
            return LtiInstructorThemeAnalysis()
        return LtiInstructorThemeAnalysis.model_validate(parsed_response)
    except Exception as e:
        logger.warning("LTI instructor theme analysis failed: %s", e)
        return LtiInstructorThemeAnalysis()


def _get_or_generate_theme_analysis(
    project_id: int,
    start: datetime,
    end: datetime,
    db_session: Session,
) -> LtiInstructorThemeAnalysis:
    cached = _get_cached_theme_analysis(project_id, start, end)
    if cached is not None:
        return cached

    questions = get_lti_project_user_messages_for_theme_analysis(
        project_id=project_id,
        start_time=start,
        end_time=end,
        db_session=db_session,
        limit=LTI_INSTRUCTOR_THEME_MESSAGE_LIMIT,
    )
    analysis = _generate_theme_analysis(questions)
    _set_cached_theme_analysis(project_id, start, end, analysis)
    return analysis


def _build_daily_trend_points(
    project_id: int,
    start: datetime,
    end: datetime,
    db_session: Session,
) -> list[LtiInstructorDailyTrend]:
    aggregates = get_lti_project_daily_query_history_aggregates(
        project_id=project_id,
        start_time=start,
        end_time=end,
        db_session=db_session,
    )
    aggregate_by_day = {aggregate.day: aggregate for aggregate in aggregates}

    daily: list[LtiInstructorDailyTrend] = []
    current_day: date = start.date()
    end_day = end.date()
    while current_day <= end_day:
        aggregate = aggregate_by_day.get(current_day)
        daily.append(
            LtiInstructorDailyTrend(
                date=current_day,
                session_count=aggregate.session_count if aggregate else 0,
                message_count=aggregate.message_count if aggregate else 0,
                positive_feedback_count=(
                    aggregate.positive_feedback_count if aggregate else 0
                ),
                negative_feedback_count=(
                    aggregate.negative_feedback_count if aggregate else 0
                ),
            )
        )
        current_day += timedelta(days=1)

    return daily


def yield_snapshot_from_chat_session(
    chat_session: ChatSession,
    db_session: Session,
) -> Generator[ChatSessionSnapshot | None]:
    yield snapshot_from_chat_session(chat_session=chat_session, db_session=db_session)


def fetch_and_process_chat_session_history(
    db_session: Session,
    start: datetime,
    end: datetime,
    limit: int | None = 500,  # noqa: ARG001
    project_id: int | None = None,
) -> Generator[ChatSessionSnapshot]:
    PAGE_SIZE = 100

    page = 0
    while True:
        paged_chat_sessions = get_page_of_chat_sessions(
            start_time=start,
            end_time=end,
            db_session=db_session,
            page_num=page,
            page_size=PAGE_SIZE,
            project_id=project_id,
        )

        if not paged_chat_sessions:
            break

        paged_snapshots = parallel_yield(
            [
                yield_snapshot_from_chat_session(
                    db_session=db_session,
                    chat_session=chat_session,
                )
                for chat_session in paged_chat_sessions
            ]
        )

        for snapshot in paged_snapshots:
            if snapshot:
                yield snapshot

        # If we've fetched *less* than a `PAGE_SIZE` worth
        # of data, we have reached the end of the
        # pagination sequence; break.
        if len(paged_chat_sessions) < PAGE_SIZE:
            break

        page += 1


def _drain_csv_buffer(buffer: io.StringIO) -> str:
    value = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return value


def stream_query_history_as_csv(
    snapshots: Iterable[ChatSessionSnapshot],
) -> Generator[str]:
    """Yield query-history CSV incrementally (header first, then one chunk per
    chat session). Used for synchronous streaming downloads; the admin export task
    drains the same generator into a single buffer so both formats stay identical."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=QUERY_HISTORY_CSV_FIELDS)
    writer.writeheader()
    yield _drain_csv_buffer(buffer)

    for snapshot in snapshots:
        writer.writerows(
            qa_pair.to_json()
            for qa_pair in QuestionAnswerPairSnapshot.from_chat_session_snapshot(
                snapshot
            )
        )
        yield _drain_csv_buffer(buffer)


def snapshot_from_chat_session(
    chat_session: ChatSession,
    db_session: Session,
) -> ChatSessionSnapshot | None:
    try:
        # Older chats may not have the right structure
        messages = create_chat_history_chain(
            chat_session_id=chat_session.id, db_session=db_session
        )
    except RuntimeError:
        return None

    flow_type = SessionType.SLACK if chat_session.onyxbot_flow else SessionType.CHAT

    return ChatSessionSnapshot(
        id=chat_session.id,
        user_email=get_display_email(
            chat_session.user.email if chat_session.user else None
        ),
        name=chat_session.description,
        messages=[
            MessageSnapshot.build(message)
            for message in messages
            if message.message_type != MessageType.SYSTEM
        ],
        assistant_id=chat_session.persona_id,
        assistant_name=chat_session.persona.name if chat_session.persona else None,
        time_created=chat_session.time_created,
        flow_type=flow_type,
    )


@router.get("/admin/chat-sessions")
def admin_get_chat_sessions(
    user_id: UUID,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ChatSessionsResponse:
    # we specifically don't allow this endpoint if "anonymized" since
    # this is a direct query on the user id
    ensure_query_history_is_enabled(
        [
            QueryHistoryType.DISABLED,
            QueryHistoryType.ANONYMIZED,
        ]
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
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[ChatSessionMinimal]:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

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
            _force_anonymized_minimal_session(minimal_chat_session)
        minimal_chat_sessions.append(minimal_chat_session)

    return PaginatedReturn(
        items=minimal_chat_sessions,
        total_items=total_filtered_chat_sessions_count,
    )


@router.get("/admin/chat-session-history/{chat_session_id}")
def get_chat_session_admin(
    chat_session_id: UUID,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ChatSessionSnapshot:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_session_id,
            user_id=None,  # view chat regardless of user
            db_session=db_session,
            include_deleted=True,
        )
    except ValueError:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            f"Chat session with id '{chat_session_id}' does not exist.",
        )
    snapshot = snapshot_from_chat_session(
        chat_session=chat_session, db_session=db_session
    )

    if snapshot is None:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            f"Could not create snapshot for chat session with id '{chat_session_id}'",
        )

    if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
        _force_anonymized_snapshot(snapshot)

    return snapshot


@router.get("/lti/instructor/query-history")
def get_lti_instructor_chat_session_history(
    project_id: int,
    page_num: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1),
    feedback_type: QAFeedbackType | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> PaginatedReturn[ChatSessionMinimal]:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])
    _ensure_lti_instructor_project_access(
        project_id=project_id,
        user=user,
        db_session=db_session,
    )

    page_of_chat_sessions = get_page_of_chat_sessions(
        page_num=page_num,
        page_size=page_size,
        db_session=db_session,
        start_time=start_time,
        end_time=end_time,
        feedback_filter=feedback_type,
        project_id=project_id,
    )

    total_filtered_chat_sessions_count = get_total_filtered_chat_sessions_count(
        db_session=db_session,
        start_time=start_time,
        end_time=end_time,
        feedback_filter=feedback_type,
        project_id=project_id,
    )

    return PaginatedReturn(
        items=[
            _force_anonymized_minimal_session(
                ChatSessionMinimal.from_chat_session(chat_session),
                redact_content=True,
            )
            for chat_session in page_of_chat_sessions
        ],
        total_items=total_filtered_chat_sessions_count,
    )


# NOTE: declared before the `/{chat_session_id}` route so the literal "export"
# path isn't captured (and rejected) as a UUID path parameter.
@router.get("/lti/instructor/query-history/export")
def export_lti_instructor_query_history(
    project_id: int,
    start: datetime,
    end: datetime,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])
    _ensure_valid_time_range(start, end)
    _ensure_lti_instructor_project_access(
        project_id=project_id,
        user=user,
        db_session=db_session,
    )

    snapshots = fetch_and_process_chat_session_history(
        db_session=db_session,
        start=start,
        end=end,
        project_id=project_id,
    )
    # Mandatory, unconditional anonymization + content redaction — identical to the
    # instructor view surfaces and independent of `ONYX_QUERY_HISTORY_TYPE`.
    redacted_snapshots = (
        _force_anonymized_snapshot(snapshot, redact_content=True)
        for snapshot in snapshots
    )

    filename = f"course-{project_id}-query-history.csv"
    return StreamingResponse(
        stream_query_history_as_csv(redacted_snapshots),
        media_type=FileType.CSV,
        headers={"Content-Disposition": f"attachment;filename={filename}"},
    )


@router.get("/lti/instructor/query-history/{chat_session_id}")
def get_lti_instructor_chat_session(
    chat_session_id: UUID,
    project_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionSnapshot:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])
    _ensure_lti_instructor_project_access(
        project_id=project_id,
        user=user,
        db_session=db_session,
    )

    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_session_id,
            user_id=None,
            db_session=db_session,
            include_deleted=True,
        )
    except ValueError:
        raise OnyxError(
            OnyxErrorCode.SESSION_NOT_FOUND,
            f"Chat session with id '{chat_session_id}' does not exist.",
        )

    if chat_session.project_id != project_id:
        raise OnyxError(
            OnyxErrorCode.SESSION_NOT_FOUND,
            f"Chat session with id '{chat_session_id}' does not exist.",
        )

    snapshot = snapshot_from_chat_session(
        chat_session=chat_session, db_session=db_session
    )
    if snapshot is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Could not create snapshot for chat session with id '{chat_session_id}'",
        )

    return _force_anonymized_snapshot(snapshot, redact_content=True)


@router.get("/lti/instructor/trends")
def get_lti_instructor_trends(
    project_id: int,
    start: datetime,
    end: datetime,
    include_themes: bool = False,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> LtiInstructorTrendsResponse:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])
    _ensure_valid_time_range(start, end)
    _ensure_lti_instructor_project_access(
        project_id=project_id,
        user=user,
        db_session=db_session,
    )

    daily = _build_daily_trend_points(
        project_id=project_id,
        start=start,
        end=end,
        db_session=db_session,
    )
    feedback = get_lti_project_feedback_aggregate(
        project_id=project_id,
        start_time=start,
        end_time=end,
        db_session=db_session,
    )
    theme_analysis = (
        _get_or_generate_theme_analysis(
            project_id=project_id,
            start=start,
            end=end,
            db_session=db_session,
        )
        if include_themes
        else None
    )

    return LtiInstructorTrendsResponse(
        start=start,
        end=end,
        total_sessions=sum(point.session_count for point in daily),
        total_messages=sum(point.message_count for point in daily),
        daily=daily,
        feedback_count=feedback.feedback_count,
        thumbs_down_count=feedback.thumbs_down_count,
        thumbs_down_rate=(
            feedback.thumbs_down_count / feedback.feedback_count
            if feedback.feedback_count
            else 0.0
        ),
        themes=theme_analysis.clusters if theme_analysis else None,
        summary=theme_analysis.summary if theme_analysis else None,
    )


@router.get("/admin/query-history/list")
def list_all_query_history_exports(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[QueryHistoryExport]:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])
    try:
        pending_tasks = [
            QueryHistoryExport.from_task(task)
            for task in get_all_query_history_export_tasks(db_session=db_session)
        ]
        generated_files = [
            QueryHistoryExport.from_file(file)
            for file in get_query_history_export_files(db_session=db_session)
        ]
        merged = pending_tasks + generated_files

        # We sort based off of the start-time of the task.
        # We also return it in reverse order since viewing generated reports in most-recent to least-recent is most common.
        merged.sort(key=lambda task: task.start_time, reverse=True)

        return merged
    except Exception as e:
        raise HTTPException(
            HTTPStatus.INTERNAL_SERVER_ERROR, f"Failed to get all tasks: {e}"
        )


@router.post("/admin/query-history/start-export", tags=PUBLIC_API_TAGS)
def start_query_history_export(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, str]:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

    start = start or datetime.fromtimestamp(0, tz=timezone.utc)
    end = end or datetime.now(tz=timezone.utc)

    if start >= end:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            f"Start time must come before end time, but instead got the start time coming after; {start=} {end=}",
        )

    task_id_uuid = uuid.uuid4()
    task_id = str(task_id_uuid)
    start_time = datetime.now(tz=timezone.utc)

    register_task(
        db_session=db_session,
        task_name=query_history_task_name(start=start, end=end),
        task_id=task_id,
        status=TaskStatus.PENDING,
        start_time=start_time,
    )

    client_app.send_task(
        OnyxCeleryTask.EXPORT_QUERY_HISTORY_TASK,
        task_id=task_id,
        priority=OnyxCeleryPriority.MEDIUM,
        queue=OnyxCeleryQueues.CSV_GENERATION,
        expires=CELERY_QUERY_HISTORY_EXPORT_TASK_EXPIRES,
        kwargs={
            "start": start,
            "end": end,
            "start_time": start_time,
            "tenant_id": get_current_tenant_id(),
        },
    )

    return {"request_id": task_id}


@router.get("/admin/query-history/export-status", tags=PUBLIC_API_TAGS)
def get_query_history_export_status(
    request_id: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

    task = get_task_with_id(db_session=db_session, task_id=request_id)

    if task:
        return {"status": task.status}

    # If task is None, then it's possible that the task has already finished processing.
    # Therefore, we should then check if the export file has already been stored inside of the file-store.
    # If that *also* doesn't exist, then we can return a 404.
    file_store = get_default_file_store()

    report_name = construct_query_history_report_name(request_id)
    has_file = file_store.has_file(
        file_id=report_name,
        file_origin=FileOrigin.QUERY_HISTORY_CSV,
        file_type=FileType.CSV,
    )

    if not has_file:
        raise HTTPException(
            HTTPStatus.NOT_FOUND,
            f"No task with {request_id=} was found",
        )

    return {"status": TaskStatus.SUCCESS}


@router.get("/admin/query-history/download", tags=PUBLIC_API_TAGS)
def download_query_history_csv(
    request_id: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    ensure_query_history_is_enabled(disallowed=[QueryHistoryType.DISABLED])

    report_name = construct_query_history_report_name(request_id)
    file_store = get_default_file_store()
    has_file = file_store.has_file(
        file_id=report_name,
        file_origin=FileOrigin.QUERY_HISTORY_CSV,
        file_type=FileType.CSV,
    )

    if has_file:
        try:
            csv_stream = file_store.read_file(report_name)
        except Exception as e:
            raise HTTPException(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"Failed to read query history file: {str(e)}",
            )
        csv_stream.seek(0)
        return StreamingResponse(
            iter(csv_stream),
            media_type=FileType.CSV,
            headers={"Content-Disposition": f"attachment;filename={report_name}"},
        )

    # If the file doesn't exist yet, it may still be processing.
    # Therefore, we check the task queue to determine its status, if there is any.
    task = get_task_with_id(db_session=db_session, task_id=request_id)
    if not task:
        raise HTTPException(
            HTTPStatus.NOT_FOUND,
            f"No task with {request_id=} was found",
        )

    if task.status in [TaskStatus.STARTED, TaskStatus.PENDING]:
        raise HTTPException(
            HTTPStatus.ACCEPTED, f"Task with {request_id=} is still being worked on"
        )

    elif task.status == TaskStatus.FAILURE:
        raise HTTPException(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            f"Task with {request_id=} failed to be processed",
        )
    else:
        # This is the final case in which `task.status == SUCCESS`
        raise RuntimeError(
            "The task was marked as success, the file was not found in the file store; this is an internal error..."
        )
