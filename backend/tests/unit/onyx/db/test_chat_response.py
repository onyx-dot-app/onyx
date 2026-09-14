"""Chat response persistence: referenced files and text sanitization."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import JsonValue, ValidationError
from pytest import MonkeyPatch

from onyx.configs.constants import MessageType
from onyx.db import chat_response
from onyx.db.chat import translate_db_message_to_chat_message_detail
from onyx.db.chat_response import _extract_referenced_file_descriptors
from onyx.db.models import ChatMessage
from onyx.file_store.models import ChatFileType
from onyx.llm.models import GenerationRequestParams, ReasoningEffort
from onyx.tools.models import PythonExecutionFile, ToolCallInfo


def _make_tool_call_info(
    generated_files: list[PythonExecutionFile] | None = None,
    tool_name: str = "run_python",
) -> ToolCallInfo:
    return ToolCallInfo(
        parent_tool_call_id=None,
        turn_index=0,
        tab_index=0,
        tool_name=tool_name,
        tool_call_id="tc_1",
        tool_id=1,
        reasoning_tokens=None,
        tool_call_arguments={"code": "print('hi')"},
        tool_call_response="{}",
        generated_files=generated_files,
    )


# ---- _extract_referenced_file_descriptors tests ----


def test_returns_empty_when_no_generated_files() -> None:
    tool_call = _make_tool_call_info(generated_files=None)
    result = _extract_referenced_file_descriptors([tool_call], "some message")
    assert result == []


def test_returns_empty_when_file_not_referenced() -> None:
    files = [
        PythonExecutionFile(
            filename="chart.png",
            file_link="http://localhost/api/chat/file/abc-123",
        )
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    result = _extract_referenced_file_descriptors([tool_call], "Here is your answer.")
    assert result == []


def test_extracts_referenced_file() -> None:
    file_id = "abc-123-def"
    files = [
        PythonExecutionFile(
            filename="chart.png",
            file_link=f"http://localhost/api/chat/file/{file_id}",
        )
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    message = (
        f"Here is the chart: [chart.png](http://localhost/api/chat/file/{file_id})"
    )

    result = _extract_referenced_file_descriptors([tool_call], message)

    assert len(result) == 1
    assert result[0]["id"] == file_id
    assert result[0]["type"] == ChatFileType.IMAGE
    assert result[0]["name"] == "chart.png"


def test_filters_unreferenced_files() -> None:
    referenced_id = "ref-111"
    unreferenced_id = "unref-222"
    files = [
        PythonExecutionFile(
            filename="chart.png",
            file_link=f"http://localhost/api/chat/file/{referenced_id}",
        ),
        PythonExecutionFile(
            filename="data.csv",
            file_link=f"http://localhost/api/chat/file/{unreferenced_id}",
        ),
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    message = f"Here is the chart: [chart.png](http://localhost/api/chat/file/{referenced_id})"

    result = _extract_referenced_file_descriptors([tool_call], message)

    assert len(result) == 1
    assert result[0]["id"] == referenced_id
    assert result[0]["name"] == "chart.png"


def test_extracts_from_multiple_tool_calls() -> None:
    id_1 = "file-aaa"
    id_2 = "file-bbb"
    tc1 = _make_tool_call_info(
        generated_files=[
            PythonExecutionFile(
                filename="plot.png",
                file_link=f"http://localhost/api/chat/file/{id_1}",
            )
        ]
    )
    tc2 = _make_tool_call_info(
        generated_files=[
            PythonExecutionFile(
                filename="report.csv",
                file_link=f"http://localhost/api/chat/file/{id_2}",
            )
        ]
    )
    message = f"[plot.png](http://localhost/api/chat/file/{id_1}) and [report.csv](http://localhost/api/chat/file/{id_2})"

    result = _extract_referenced_file_descriptors([tc1, tc2], message)

    assert len(result) == 2
    ids = {d["id"] for d in result}
    assert ids == {id_1, id_2}


def test_csv_file_type() -> None:
    file_id = "csv-123"
    files = [
        PythonExecutionFile(
            filename="data.csv",
            file_link=f"http://localhost/api/chat/file/{file_id}",
        )
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    message = f"[data.csv](http://localhost/api/chat/file/{file_id})"

    result = _extract_referenced_file_descriptors([tool_call], message)

    assert len(result) == 1
    assert result[0]["type"] == ChatFileType.TABULAR


def test_unknown_extension_defaults_to_plain_text() -> None:
    file_id = "bin-456"
    files = [
        PythonExecutionFile(
            filename="output.xyz",
            file_link=f"http://localhost/api/chat/file/{file_id}",
        )
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    message = f"[output.xyz](http://localhost/api/chat/file/{file_id})"

    result = _extract_referenced_file_descriptors([tool_call], message)

    assert len(result) == 1
    assert result[0]["type"] == ChatFileType.PLAIN_TEXT


def test_skips_tool_calls_without_generated_files() -> None:
    file_id = "img-789"
    tc_no_files = _make_tool_call_info(generated_files=None)
    tc_empty = _make_tool_call_info(generated_files=[])
    tc_with_files = _make_tool_call_info(
        generated_files=[
            PythonExecutionFile(
                filename="result.png",
                file_link=f"http://localhost/api/chat/file/{file_id}",
            )
        ]
    )
    message = f"[result.png](http://localhost/api/chat/file/{file_id})"

    result = _extract_referenced_file_descriptors(
        [tc_no_files, tc_empty, tc_with_files], message
    )

    assert len(result) == 1
    assert result[0]["id"] == file_id


def test_save_chat_turn_sanitizes_message_and_reasoning(
    monkeypatch: MonkeyPatch,
) -> None:
    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = [1, 2, 3]
    monkeypatch.setattr(
        chat_response, "get_tokenizer", lambda *_a, **_kw: mock_tokenizer
    )

    mock_msg = MagicMock()
    mock_msg.id = 1
    mock_msg.chat_session_id = "test"
    mock_msg.files = None

    mock_session = MagicMock()

    chat_response.save_chat_turn(
        message_text="hello\x00world\ud800",
        reasoning_tokens="think\x00ing\udfff",
        tool_calls=[],
        citation_to_doc={},
        all_search_docs={},
        db_session=mock_session,
        assistant_message=mock_msg,
        request_params=GenerationRequestParams(
            model_name="test",
            model_provider="openai",
            reasoning_effort=ReasoningEffort.LOW,
            max_tokens=None,
            sent_kwargs={"temperature": 0.2},
        ),
    )

    assert mock_msg.message == "helloworld"
    assert mock_msg.reasoning_tokens == "thinking"

    assert mock_msg.request_params == {
        "model_name": "test",
        "model_provider": "openai",
        "reasoning_effort": "low",
        "max_tokens": None,
        "sent_kwargs": {"temperature": 0.2},
    }


def test_chat_detail_validates_stored_request_parameters() -> None:
    message = ChatMessage(
        id=1,
        chat_session_id=uuid4(),
        message="answer",
        token_count=1,
        message_type=MessageType.ASSISTANT,
        time_sent=datetime.now(timezone.utc),
        search_docs=[],
        chat_message_feedbacks=[],
        request_params={
            "model_name": "test",
            "model_provider": "openai",
            "reasoning_effort": "low",
            "max_tokens": None,
            "sent_kwargs": {"temperature": 0.2},
        },
    )
    detail = translate_db_message_to_chat_message_detail(message)
    assert detail.request_params is not None
    assert detail.request_params.model_dump(mode="json") == message.request_params
    message.request_params = None
    assert translate_db_message_to_chat_message_detail(message).request_params is None
    invalid_params: dict[str, JsonValue] = {"model_name": "incomplete"}
    message.request_params = invalid_params
    with pytest.raises(ValidationError):
        translate_db_message_to_chat_message_detail(message)
