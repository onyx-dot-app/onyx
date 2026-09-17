import re
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.chat import create_chat_session
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.answer.stream_test_utils import final_answer
from tests.external_dependency_unit.conftest import create_test_user
from tests.utils.secret_names import TestSecret


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_stream_chat_current_date_response(
    db_session: Session,
    full_deployment_setup: None,  # noqa: ARG001
    mock_external_deps: None,  # noqa: ARG001
) -> None:
    """Smoke test that asking for current date yields a streamed response.

    This exercises the full chat path using the default persona, ensuring
    the system prompt makes it to the LLM and a response is returned.
    """
    # Ensure LLM provider exists
    ensure_default_llm_provider(db_session)

    # Create user, persona, session
    test_user: User = create_test_user(db_session, email_prefix="test_current_date")
    default_persona = get_persona_by_id(
        persona_id=0, user=test_user, db_session=db_session, is_for_edit=False
    )
    chat_session = create_chat_session(
        db_session=db_session,
        description="Test current date question",
        user_id=test_user.id if test_user else None,
        persona_id=default_persona.id,
    )

    chat_request = SendMessageRequest(
        message="Please respond only with the current date in the format 'Weekday Month DD, YYYY'.",
        chat_session_id=chat_session.id,
    )

    gen = handle_stream_message_objects(
        new_msg_req=chat_request,
        user=test_user,
    )

    raw = list(gen)
    content = final_answer(raw)
    assert any(isinstance(part, MessageResponseIDInfo) for part in raw)

    # Validate the response contains a properly formatted current date string
    match = re.search(r"[A-Za-z]+ [A-Za-z]+ \d{1,2}, \d{4}", content)
    assert match, f"Expected a date in content, got: {content[:200]}..."

    timestamp_str = match.group(0)
    timestamp_dt = datetime.strptime(timestamp_str, "%A %B %d, %Y")
    now = datetime.now()

    assert timestamp_dt.strftime("%A") == now.strftime("%A"), (
        f"Expected weekday {now.strftime('%A')}, got {timestamp_dt.strftime('%A')}"
    )
    assert timestamp_dt.strftime("%B") == now.strftime("%B"), (
        f"Expected month {now.strftime('%B')}, got {timestamp_dt.strftime('%B')}"
    )
    assert timestamp_dt.day == now.day and timestamp_dt.year == now.year, (
        f"Expected day {now.strftime('%d')} and year {now.strftime('%Y')}, "
        f"got {timestamp_dt.strftime('%d')} {timestamp_dt.strftime('%Y')}"
    )
