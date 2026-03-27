import pytest

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
