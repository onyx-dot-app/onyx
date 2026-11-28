"""The ``chat.message_send`` event of a finished chat response."""

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from onyx.chat.execution import ChatTurnExecution
from onyx.chat.models import (
    ChatResponseOutcome,
    ChatResponseSnapshot,
    PersistenceStatus,
)
from onyx.chat.persistence import ChatResponsePersistence
from onyx.db.enums import IncognitoRecordMode
from onyx.utils.audit import AUDIT_DOCUMENT_ID_CAP, AuditActor, AuditEventCategory
from tests.utils.audit import events_for, use_audit_settings

pytestmark = pytest.mark.usefixtures("enterprise_audit")


def _execution(incognito_record_mode: IncognitoRecordMode | None) -> Any:
    return SimpleNamespace(
        setup=SimpleNamespace(
            chat_session_id=uuid4(),
            user_message_id=11,
            persona_id=3,
            incognito_record_mode=incognito_record_mode,
            resumed_response_id=None,
            new_msg_req=SimpleNamespace(
                message="what is our refund policy?", origin="webapp"
            ),
        ),
        _audit_actor=AuditActor(user_id="u-1"),
    )


def _persistence() -> ChatResponsePersistence:
    return cast(
        ChatResponsePersistence,
        SimpleNamespace(
            message_id=12,
            model_index=0,
            llm=SimpleNamespace(
                config=SimpleNamespace(model_provider="openai", model_name="gpt-x")
            ),
        ),
    )


def _response(
    retrieved: int, persistence_status: PersistenceStatus = PersistenceStatus.SAVED
) -> ChatResponseOutcome:
    # Detached snapshot: only the fields the event reads.
    snapshot = ChatResponseSnapshot.model_construct(
        tool_calls=[
            SimpleNamespace(tool_name="run_search"),
            SimpleNamespace(tool_name="run_search"),
        ],
        all_search_docs={f"doc-{i}": object() for i in range(retrieved)},
        citation_info=[SimpleNamespace(document_id="doc-1")],
        cancelled=False,
        error=None,
    )
    return ChatResponseOutcome.model_construct(
        response=snapshot, persistence_status=persistence_status
    )


def test_event_lists_what_the_user_saw(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    use_audit_settings(
        monkeypatch, categories=(AuditEventCategory.CHAT,), include_query_text=True
    )
    execution = _execution(incognito_record_mode=None)

    ChatTurnExecution._emit_message_audit(
        execution, _persistence(), _response(AUDIT_DOCUMENT_ID_CAP + 5)
    )

    (event,) = events_for(caplog, "chat.message_send")
    extra = event["extra"]
    assert event["outcome"] == "success"
    assert event["resource_id"] == str(execution.setup.chat_session_id)
    assert extra["assistant_message_id"] == 12
    assert extra["model_name"] == "gpt-x"
    assert extra["tool_names"] == ["run_search"]
    assert len(extra["retrieved_document_ids"]) == AUDIT_DOCUMENT_ID_CAP
    assert extra["retrieved_document_ids_truncated"] is True
    assert extra["cited_document_ids"] == ["doc-1"]
    assert extra["query_text"] == "what is our refund policy?"


def test_incognito_chat_keeps_content_out(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    use_audit_settings(
        monkeypatch, categories=(AuditEventCategory.CHAT,), include_query_text=True
    )

    ChatTurnExecution._emit_message_audit(
        _execution(incognito_record_mode=IncognitoRecordMode.USAGE_ONLY),
        _persistence(),
        _response(2),
    )

    (event,) = events_for(caplog, "chat.message_send")
    assert event["extra"]["incognito"] is True
    assert "retrieved_document_ids" not in event["extra"]
    assert "query_text" not in event["extra"]


def test_chat_events_are_off_by_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    use_audit_settings(monkeypatch)

    ChatTurnExecution._emit_message_audit(
        _execution(incognito_record_mode=None), _persistence(), _response(1)
    )

    assert events_for(caplog, "chat.message_send") == []


def test_failed_worker_still_writes_a_failure_event(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    use_audit_settings(monkeypatch, categories=(AuditEventCategory.CHAT,))

    ChatTurnExecution._emit_message_audit(
        _execution(incognito_record_mode=None), _persistence(), None
    )

    (event,) = events_for(caplog, "chat.message_send")
    assert event["outcome"] == "failure"
    assert event["extra"]["error"] is True
    assert "retrieved_document_ids" not in event["extra"]


def test_a_response_that_failed_to_save_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    use_audit_settings(monkeypatch, categories=(AuditEventCategory.CHAT,))

    ChatTurnExecution._emit_message_audit(
        _execution(incognito_record_mode=None),
        _persistence(),
        _response(1, PersistenceStatus.FAILED),
    )

    (event,) = events_for(caplog, "chat.message_send")
    assert event["outcome"] == "failure"
    assert event["extra"]["error"] is True
