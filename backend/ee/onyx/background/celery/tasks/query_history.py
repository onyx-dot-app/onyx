import csv
import io
from datetime import datetime

from sqlalchemy.orm import Session

from ee.onyx.server.query_history.models import ChatSessionSnapshot
from ee.onyx.server.query_history.models import QuestionAnswerPairSnapshot
from ee.onyx.server.query_history.utils import fetch_and_process_chat_session_history
from ee.onyx.server.query_history.utils import ONYX_ANONYMIZED_EMAIL
from onyx.configs.app_configs import ONYX_QUERY_HISTORY_TYPE
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import QueryHistoryType
from onyx.file_store.file_store import get_default_file_store


def query_history_report(
    db_session: Session, request_id: str, start: datetime, end: datetime
) -> str:
    chat_session_history = fetch_chat_session_history(
        db_session=db_session, start=start, end=end
    )
    qa_pairs = construct_qa_pairs(chat_session_history)
    persist_chat_session_history(
        db_session=db_session,
        report_name=f"query_history_report_{request_id}.csv",
        qa_pairs=qa_pairs,
    )


def fetch_chat_session_history(
    db_session: Session, start: datetime, end: datetime
) -> list[ChatSessionSnapshot]:
    return fetch_and_process_chat_session_history(
        db_session=db_session,
        start=start,
        end=end,
        feedback_type=None,
        limit=None,
    )


def construct_qa_pairs(
    chat_session_history: list[ChatSessionSnapshot],
) -> list[QuestionAnswerPairSnapshot]:
    qa_pairs: list[QuestionAnswerPairSnapshot] = []
    for chat_session_snapshot in chat_session_history:
        if ONYX_QUERY_HISTORY_TYPE == QueryHistoryType.ANONYMIZED:
            chat_session_snapshot.user_email = ONYX_ANONYMIZED_EMAIL

        qa_pairs.extend(
            QuestionAnswerPairSnapshot.from_chat_session_snapshot(chat_session_snapshot)
        )

    return qa_pairs


def persist_chat_session_history(
    db_session: Session, report_name: str, qa_pairs: list[QuestionAnswerPairSnapshot]
):
    file_store = get_default_file_store(db_session)
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream, fieldnames=list(QuestionAnswerPairSnapshot.model_fields.keys())
    )

    writer.writeheader()
    for row in qa_pairs:
        writer.writerow(row.to_json())

    stream.seek(0)
    file_store.save_file(
        file_name=report_name,
        content=stream,
        display_name=report_name,
        file_origin=FileOrigin.GENERATED_REPORT,
        file_type="text/csv",
    )
