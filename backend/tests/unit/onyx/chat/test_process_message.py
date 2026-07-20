import pytest
from types import SimpleNamespace
from uuid import uuid4

from onyx.chat.process_message import _collect_available_file_ids
from onyx.chat.process_message import _resolve_query_processing_hook_result
from onyx.chat.process_message import remove_answer_citations
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.executor import HookSkipped
from onyx.hooks.executor import HookSoftFailed
from onyx.hooks.points.query_processing import QueryProcessingResponse


def test_remove_answer_citations_strips_http_markdown_citation() -> None:
    answer = "The answer is Paris [[1]](https://example.com/doc)."

    assert remove_answer_citations(answer) == "The answer is Paris."


def test_remove_answer_citations_strips_empty_markdown_citation() -> None:
    answer = "The answer is Paris [[1]]()."

    assert remove_answer_citations(answer) == "The answer is Paris."


def test_remove_answer_citations_strips_citation_with_parentheses_in_url() -> None:
    answer = (
        "The answer is Paris "
        "[[1]](https://en.wikipedia.org/wiki/Function_(mathematics))."
    )

    assert remove_answer_citations(answer) == "The answer is Paris."


def test_remove_answer_citations_preserves_non_citation_markdown_links() -> None:
    answer = (
        "See [reference](https://example.com/Function_(mathematics)) "
        "for context [[1]](https://en.wikipedia.org/wiki/Function_(mathematics))."
    )

    assert (
        remove_answer_citations(answer)
        == "See [reference](https://example.com/Function_(mathematics)) for context."
    )


# ---------------------------------------------------------------------------
# Query Processing hook response handling (_resolve_query_processing_hook_result)
# ---------------------------------------------------------------------------


def test_hook_skipped_leaves_message_text_unchanged() -> None:
    result = _resolve_query_processing_hook_result(HookSkipped(), "original query")
    assert result == "original query"


def test_hook_soft_failed_leaves_message_text_unchanged() -> None:
    result = _resolve_query_processing_hook_result(HookSoftFailed(), "original query")
    assert result == "original query"


def test_null_query_raises_query_rejected() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(query=None), "original query"
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_empty_string_query_raises_query_rejected() -> None:
    """Empty string is falsy — must be treated as rejection, same as None."""
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(query=""), "original query"
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_whitespace_only_query_raises_query_rejected() -> None:
    """Whitespace-only string is truthy but meaningless — must be treated as rejection."""
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(query="   "), "original query"
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_absent_query_field_raises_query_rejected() -> None:
    """query defaults to None when not provided."""
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(), "original query"
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_rejection_message_surfaced_in_error_when_provided() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(
                query=None, rejection_message="Queries about X are not allowed."
            ),
            "original query",
        )
    assert "Queries about X are not allowed." in str(exc_info.value)


def test_fallback_rejection_message_when_none() -> None:
    """No rejection_message → generic fallback used in OnyxError detail."""
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(query=None, rejection_message=None),
            "original query",
        )
    assert "No rejection reason was provided." in str(exc_info.value)


def test_nonempty_query_rewrites_message_text() -> None:
    result = _resolve_query_processing_hook_result(
        QueryProcessingResponse(query="rewritten query"), "original query"
    )
    assert result == "rewritten query"


def test_collect_available_file_ids_uses_user_file_id_for_chat_uploads() -> None:
    user_file_id = uuid4()
    file_store_id = uuid4()
    chat_history = [
        SimpleNamespace(
            files=[
                {
                    "id": str(file_store_id),
                    "user_file_id": str(user_file_id),
                }
            ]
        )
    ]

    available = _collect_available_file_ids(
        chat_history=chat_history,  # type: ignore[arg-type]
        project_id=None,
        user_id=None,
        db_session=None,  # type: ignore[arg-type]
    )

    assert user_file_id in available.user_file_ids
    assert len(available.user_file_ids) == 1
    assert available.chat_file_ids == []


def test_collect_available_file_ids_uses_chat_id_without_user_file_id() -> None:
    file_store_id = uuid4()
    chat_history = [SimpleNamespace(files=[{"id": str(file_store_id)}])]

    available = _collect_available_file_ids(
        chat_history=chat_history,  # type: ignore[arg-type]
        project_id=None,
        user_id=None,
        db_session=None,  # type: ignore[arg-type]
    )

    assert available.user_file_ids == []
    assert available.chat_file_ids == [file_store_id]
