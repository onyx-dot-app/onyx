import uuid
from collections.abc import Generator
from datetime import datetime
from typing import IO
from typing import Optional

from fastapi_users_db_sqlalchemy import UUID_ID
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from ee.onyx.db.query_history import fetch_chat_sessions_eagerly_by_time
from ee.onyx.server.reporting.usage_export_models import ChatMessageSkeleton
from ee.onyx.server.reporting.usage_export_models import FlowType
from ee.onyx.server.reporting.usage_export_models import UsageReportMetadata
from onyx.configs.constants import MessageType
from onyx.db.models import UsageReport
from onyx.db.models import User
from onyx.file_store.file_store import get_default_file_store


# Gets skeletons of all messages in the given range
def get_empty_chat_messages_entries__paginated(
    db_session: Session,
    period: tuple[datetime, datetime],
    limit: int | None = 500,
    initial_time: datetime | None = None,
) -> tuple[Optional[datetime], list[ChatMessageSkeleton]]:
    """Returns a tuple where:
    first element is the most recent timestamp out of the sessions iterated
    - this timestamp can be used to paginate forward in time
    second element is a list of messages belonging to all the sessions iterated

    Only messages of type USER are returned
    """
    chat_sessions = fetch_chat_sessions_eagerly_by_time(
        start=period[0],
        end=period[1],
        db_session=db_session,
        limit=limit,
        initial_time=initial_time,
    )

    message_skeletons: list[ChatMessageSkeleton] = []
    for chat_session in chat_sessions:
        flow_type = FlowType.SLACK if chat_session.onyxbot_flow else FlowType.CHAT

        for message in chat_session.messages:
            # Only count user messages
            if message.message_type != MessageType.USER:
                continue

            # Get user email
            user_email = chat_session.user.email if chat_session.user else None

            # Get assistant name (from session persona, or alternate if specified)
            assistant_name = None
            if message.alternate_assistant_id:
                # If there's an alternate assistant, we need to fetch it
                from onyx.db.models import Persona

                alternate_persona = (
                    db_session.query(Persona)
                    .filter(Persona.id == message.alternate_assistant_id)
                    .first()
                )
                if alternate_persona:
                    assistant_name = alternate_persona.name
            elif chat_session.persona:
                assistant_name = chat_session.persona.name

            message_skeletons.append(
                ChatMessageSkeleton(
                    message_id=message.id,
                    chat_session_id=chat_session.id,
                    user_id=str(chat_session.user_id) if chat_session.user_id else None,
                    flow_type=flow_type,
                    time_sent=message.time_sent,
                    assistant_name=assistant_name,
                    user_email=user_email,
                    number_of_tokens=message.token_count,
                )
            )
    if len(chat_sessions) == 0:
        return None, []

    return chat_sessions[-1].time_created, message_skeletons


def get_all_empty_chat_message_entries(
    db_session: Session,
    period: tuple[datetime, datetime],
) -> Generator[list[ChatMessageSkeleton], None, None]:
    """period is the range of time over which to fetch messages."""
    initial_time: Optional[datetime] = period[0]
    while True:
        # iterate from oldest to newest
        time_created, message_skeletons = get_empty_chat_messages_entries__paginated(
            db_session,
            period,
            initial_time=initial_time,
        )

        if not message_skeletons:
            return

        yield message_skeletons

        # Update initial_time for the next iteration
        initial_time = time_created


def get_all_usage_reports(db_session: Session) -> list[UsageReportMetadata]:
    # Get the user emails
    usage_reports = db_session.query(UsageReport).all()
    user_ids = {r.requestor_user_id for r in usage_reports if r.requestor_user_id}
    user_emails = {
        user.id: user.email
        for user in db_session.query(User)
        .filter(cast(User.id, UUID).in_(user_ids))
        .all()
    }

    return [
        UsageReportMetadata(
            report_name=r.report_name,
            requestor=(
                user_emails.get(r.requestor_user_id) if r.requestor_user_id else None
            ),
            time_created=r.time_created,
            period_from=r.period_from,
            period_to=r.period_to,
        )
        for r in usage_reports
    ]


def get_usage_report_data(
    report_display_name: str,
) -> IO:
    """
    Get the usage report data from the file store.

    Args:
        db_session: The database session.
        report_display_name: The display name of the usage report. Also assumes
                             that the file is stored with this as the ID in the file store.

    Returns:
        The usage report data.
    """
    file_store = get_default_file_store()
    # usage report may be very large, so don't load it all into memory
    return file_store.read_file(
        file_id=report_display_name, mode="b", use_tempfile=True
    )


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
