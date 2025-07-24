from datetime import datetime
from datetime import timedelta
from datetime import timezone

from ee.onyx.db.usage_export import get_all_empty_chat_message_entries
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.seeding.chat_history_seeding import seed_chat_history


def test_usage_reports(reset: None) -> None:
    EXPECTED_SESSIONS = 2048
    MESSAGES_PER_SESSION = 4

    # divide by 2 because only messages of type USER are returned
    EXPECTED_MESSAGES = EXPECTED_SESSIONS * MESSAGES_PER_SESSION / 2

    seed_chat_history(EXPECTED_SESSIONS, MESSAGES_PER_SESSION, 90)

    with get_session_with_current_tenant() as db_session:
        # count of all entries should be exact
        period = (
            datetime.fromtimestamp(0, tz=timezone.utc),
            datetime.now(tz=timezone.utc),
        )

        count = 0
        for entry_batch in get_all_empty_chat_message_entries(db_session, period):
            for entry in entry_batch:
                count += 1

        assert count == EXPECTED_MESSAGES

        # count in a one month time range should be within a certain range statistically
        # this can be improved if we seed the chat history data deterministically
        period = (
            datetime.now(tz=timezone.utc) - timedelta(days=30),
            datetime.now(tz=timezone.utc),
        )

        count = 0
        for entry_batch in get_all_empty_chat_message_entries(db_session, period):
            for entry in entry_batch:
                count += 1

        lower = EXPECTED_MESSAGES // 3 - (EXPECTED_MESSAGES // (3 * 3))
        upper = EXPECTED_MESSAGES // 3 + (EXPECTED_MESSAGES // (3 * 3))
        assert count > lower
        assert count < upper
