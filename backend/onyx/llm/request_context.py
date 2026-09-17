import contextvars
from typing import Any

_LLM_MOCK_RESPONSE_CONTEXTVAR: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("llm_mock_response", default=None)
)

_LLM_REQUEST_PARAMS_CONTEXTVAR: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar("llm_request_params", default=None)
)


def get_llm_request_params() -> dict[str, Any] | None:
    return _LLM_REQUEST_PARAMS_CONTEXTVAR.get()


def set_llm_request_params(params: dict[str, Any] | None) -> None:
    _LLM_REQUEST_PARAMS_CONTEXTVAR.set(params)


def clear_llm_request_params() -> None:
    """Clear before a turn, so a pooled worker cannot read a stale value."""
    _LLM_REQUEST_PARAMS_CONTEXTVAR.set(None)


def get_llm_mock_response() -> str | None:
    return _LLM_MOCK_RESPONSE_CONTEXTVAR.get()


def set_llm_mock_response(mock_response: str | None) -> contextvars.Token[str | None]:
    return _LLM_MOCK_RESPONSE_CONTEXTVAR.set(mock_response)


def reset_llm_mock_response(token: contextvars.Token[str | None]) -> None:
    try:
        _LLM_MOCK_RESPONSE_CONTEXTVAR.reset(token)
    except ValueError:
        # Streaming requests can cross execution contexts.
        # Best effort clear to avoid crashing request teardown in integration mode.
        _LLM_MOCK_RESPONSE_CONTEXTVAR.set(None)
