import contextvars

from onyx.llm.request_context import get_llm_mock_response
from onyx.llm.request_context import reset_llm_mock_response
from onyx.llm.request_context import set_llm_mock_response


def test_reset_llm_mock_response_same_context() -> None:
    token = set_llm_mock_response("mock-response")
    assert get_llm_mock_response() == "mock-response"

    reset_llm_mock_response(token)
    assert get_llm_mock_response() is None


def test_reset_llm_mock_response_different_context() -> None:
    foreign_context = contextvars.copy_context()
    foreign_token = foreign_context.run(set_llm_mock_response, "foreign-response")

    set_llm_mock_response("current-response")
    assert get_llm_mock_response() == "current-response"

    # Should not raise even when token came from another context.
    reset_llm_mock_response(foreign_token)
    assert get_llm_mock_response() is None
