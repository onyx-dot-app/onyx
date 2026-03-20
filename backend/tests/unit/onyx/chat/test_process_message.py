import pytest

from onyx.chat.process_message import _apply_query_processing_hook
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
# Query Processing hook response handling (_apply_query_processing_hook)
# ---------------------------------------------------------------------------


def test_wrong_model_type_raises_internal_error() -> None:
    """If the executor ever returns an unexpected BaseModel type, raise INTERNAL_ERROR
    rather than an AssertionError or AttributeError."""
    from pydantic import BaseModel as PydanticBaseModel

    class _OtherModel(PydanticBaseModel):
        pass

    with pytest.raises(OnyxError) as exc_info:
        _apply_query_processing_hook(_OtherModel(), "original query")
    assert exc_info.value.error_code is OnyxErrorCode.INTERNAL_ERROR


def test_hook_skipped_leaves_message_text_unchanged() -> None:
    result = _apply_query_processing_hook(HookSkipped(), "original query")
    assert result == "original query"


def test_hook_soft_failed_leaves_message_text_unchanged() -> None:
    result = _apply_query_processing_hook(HookSoftFailed(), "original query")
    assert result == "original query"


def test_null_query_raises_query_rejected() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _apply_query_processing_hook(
            QueryProcessingResponse(query=None), "original query"
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_empty_string_query_raises_query_rejected() -> None:
    """Empty string is falsy — must be treated as rejection, same as None."""
    with pytest.raises(OnyxError) as exc_info:
        _apply_query_processing_hook(
            QueryProcessingResponse(query=""), "original query"
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_absent_query_field_raises_query_rejected() -> None:
    """query defaults to None when not provided."""
    with pytest.raises(OnyxError) as exc_info:
        _apply_query_processing_hook(QueryProcessingResponse(), "original query")
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_rejection_message_surfaced_in_error_when_provided() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _apply_query_processing_hook(
            QueryProcessingResponse(
                query=None, rejection_message="Queries about X are not allowed."
            ),
            "original query",
        )
    assert "Queries about X are not allowed." in str(exc_info.value)


def test_fallback_rejection_message_when_none() -> None:
    """No rejection_message → generic fallback used in OnyxError detail."""
    with pytest.raises(OnyxError) as exc_info:
        _apply_query_processing_hook(
            QueryProcessingResponse(query=None, rejection_message=None),
            "original query",
        )
    assert "Your query was rejected." in str(exc_info.value)


def test_nonempty_query_rewrites_message_text() -> None:
    result = _apply_query_processing_hook(
        QueryProcessingResponse(query="rewritten query"), "original query"
    )
    assert result == "rewritten query"
