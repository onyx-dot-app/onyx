import uuid
from collections.abc import Generator
from datetime import datetime
from typing import IO

from fastapi_users_db_sqlalchemy import UUID_ID
from sqlalchemy.orm import Session

from danswer.configs.constants import MessageType
from danswer.db.models import UsageReport
from danswer.file_store.file_store import get_default_file_store
from ee.danswer.db.query_history import fetch_chat_sessions_eagerly_by_time
from ee.danswer.server.reporting.usage_export_models import ChatMessageSkeleton
from ee.danswer.server.reporting.usage_export_models import FlowType
from ee.danswer.server.reporting.usage_export_models import UsageReportMetadata


# Gets skeletons of all message
def get_empty_chat_messages_entries__paginated(
    db_session: Session,
    period: tuple[datetime, datetime],
    limit: int | None = 1,
    initial_id: int | None = None,
) -> list[ChatMessageSkeleton]:
    chat_sessions = fetch_chat_sessions_eagerly_by_time(
        period[0], period[1], db_session, limit=limit, initial_id=initial_id
    )

    message_skeletons: list[ChatMessageSkeleton] = []
    for chat_session in chat_sessions:
        if chat_session.one_shot:
            flow_type = FlowType.SEARCH
        elif chat_session.danswerbot_flow:
            flow_type = FlowType.SLACK
        else:
            flow_type = FlowType.CHAT

        for message in chat_session.messages:
            # only count user messages
            if message.message_type != MessageType.USER:
                continue

            message_skeletons.append(
                ChatMessageSkeleton(
                    message_id=chat_session.id,
                    chat_session_id=chat_session.id,
                    user_id=str(chat_session.user_id) if chat_session.user_id else None,
                    flow_type=flow_type,
                    time_sent=message.time_sent,
                )
            )

    return message_skeletons


def get_all_empty_chat_message_entries(
    db_session: Session,
    period: tuple[datetime, datetime],
) -> Generator[list[ChatMessageSkeleton], None, None]:
    initial_id = None
    while True:
        message_skeletons = get_empty_chat_messages_entries__paginated(
            db_session, period, initial_id=initial_id
        )
        if not message_skeletons:
            return

        yield message_skeletons
        initial_id = message_skeletons[-1].message_id


def get_all_usage_reports(db_session: Session) -> list[UsageReportMetadata]:
    return [
        UsageReportMetadata(
            report_name=r.report_name,
            requestor=str(r.requestor_user_id) if r.requestor_user_id else None,
            time_created=r.time_created,
            period_from=r.period_from,
            period_to=r.period_to,
        )
        for r in db_session.query(UsageReport).all()
    ]


def get_usage_report_data(
    db_session: Session,
    report_name: str,
) -> IO:
    file_store = get_default_file_store(db_session)
    # usage report may be very large, so don't load it all into memory
    return file_store.read_file(file_name=report_name, mode="b", use_tempfile=True)


def write_usage_report(
    db_session: Session,
    report_name: str,
    user_id: uuid.UUID | UUID_ID | None,
    period: tuple[datetime, datetime] | None,
) -> UsageReport:
    new_report = UsageReport(
        report_name=report_name,
        requestor_user_id=user_id,
        period_from=period[0] if period else None,
        period_to=period[1] if period else None,
    )
    db_session.add(new_report)
    db_session.commit()
    return new_report
