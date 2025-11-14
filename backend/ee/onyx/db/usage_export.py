import uuid
from collections.abc import Generator
from datetime import datetime
from typing import IO, Optional

from fastapi_users_db_sqlalchemy import UUID_ID
from sqlalchemy.orm import Session

from ee.onyx.db.query_history import fetch_chat_sessions_eagerly_by_time
from ee.onyx.server.reporting.usage_export_models import (
    ChatMessageSkeleton,
    FlowType,
    UsageReportMetadata,
)
from onyx.configs.constants import MessageType
from onyx.db.models import UsageReport
from onyx.file_store.file_store import get_default_file_store


def _create_message_skeleton(
    msg_id: int,
    session_id: int,
    user_uuid: Optional[uuid.UUID],
    flow: FlowType,
    timestamp: datetime,
) -> ChatMessageSkeleton:
    """Формирует скелет сообщения чата."""
    return ChatMessageSkeleton(
        message_id=msg_id,
        chat_session_id=session_id,
        user_id=str(user_uuid) if user_uuid else None,
        flow_type=flow,
        time_sent=timestamp,
    )


def get_empty_chat_messages_entries__paginated(
    db_session: Session,
    period: tuple[datetime, datetime],
    limit: int | None = 500,
    initial_time: datetime | None = None,
) -> tuple[Optional[datetime], list[ChatMessageSkeleton]]:
    """
    Возвращает пагинированные скелеты пользовательских сообщений чата.
    Первый элемент - время последней сессии для пагинации.
    Второй - список скелетов сообщений.
    """
    session = db_session
    time_range = period

    fetched_sessions = fetch_chat_sessions_eagerly_by_time(
        start=time_range[0],
        end=time_range[1],
        db_session=session,
        limit=limit,
        initial_time=initial_time,
    )

    skeletons_list: list[ChatMessageSkeleton] = []
    session_count = len(fetched_sessions)
    idx = 0
    while idx < session_count:
        current_session = fetched_sessions[idx]
        session_flow = (
            FlowType.SLACK if current_session.onyxbot_flow else FlowType.CHAT
        )

        msg_count = len(current_session.messages)
        msg_idx = 0
        while msg_idx < msg_count:
            current_msg = current_session.messages[msg_idx]
            if current_msg.message_type != MessageType.USER:
                msg_idx += 1
                continue

            skeletons_list.append(
                _create_message_skeleton(
                    current_msg.id,
                    current_session.id,
                    current_session.user_id,
                    session_flow,
                    current_msg.time_sent,
                )
            )
            msg_idx += 1
        idx += 1

    if session_count == 0:
        return None, []

    return fetched_sessions[-1].time_created, skeletons_list


def get_all_empty_chat_message_entries(
    db_session: Session,
    period: tuple[datetime, datetime],
) -> Generator[list[ChatMessageSkeleton], None, None]:
    """Генерирует батчи скелетов сообщений в указанном временном диапазоне."""
    session = db_session
    time_bounds = period
    next_start: Optional[datetime] = time_bounds[0]

    while next_start is not None:
        last_timestamp, batch_skeletons = get_empty_chat_messages_entries__paginated(
            db_session=session,
            period=time_bounds,
            initial_time=next_start,
        )

        if not batch_skeletons:
            return

        yield batch_skeletons
        next_start = last_timestamp


def get_all_usage_reports(db_session: Session) -> list[UsageReportMetadata]:
    """Извлекает метаданные всех отчетов использования."""
    session = db_session
    reports = session.query(UsageReport).all()
    metadata_list: list[UsageReportMetadata] = []
    idx = 0
    reports_count = len(reports)
    while idx < reports_count:
        current_report = reports[idx]
        metadata_list.append(
            UsageReportMetadata(
                report_name=current_report.report_name,
                requestor=str(current_report.requestor_user_id)
                if current_report.requestor_user_id
                else None,
                time_created=current_report.time_created,
                period_from=current_report.period_from,
                period_to=current_report.period_to,
            )
        )
        idx += 1
    return metadata_list


def get_usage_report_data(
    db_session: Session,
    report_name: str,
) -> IO:
    """Читает данные отчета использования как бинарный поток."""
    store = get_default_file_store(db_session)
    return store.read_file(file_name=report_name, mode="b", use_tempfile=True)


def write_usage_report(
    db_session: Session,
    report_name: str,
    user_id: uuid.UUID | UUID_ID | None,
    period: tuple[datetime, datetime] | None,
) -> UsageReport:
    """Создает и сохраняет запись отчета использования."""
    session = db_session
    filename = report_name
    requester_id = user_id
    time_period = period

    new_entry = UsageReport(
        report_name=filename,
        requestor_user_id=requester_id,
        period_from=time_period[0] if time_period else None,
        period_to=time_period[1] if time_period else None,
    )
    session.add(new_entry)
    session.commit()
    return new_entry
