import contextvars
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .spans import Span
    from .traces import Trace

_current_span: contextvars.ContextVar["Span[Any] | None"] = contextvars.ContextVar(
    "current_span", default=None
)

_current_trace: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar(
    "current_trace", default=None
)


class Scope:
    """
    Manages the current span and trace in the context.
    """

    @classmethod
    def get_current_span(cls) -> "Span[Any] | None":
        return _current_span.get()

    @classmethod
    def set_current_span(
        cls, span: "Span[Any] | None"
    ) -> "contextvars.Token[Span[Any] | None]":
        return _current_span.set(span)

    @classmethod
    def reset_current_span(cls, token: "contextvars.Token[Span[Any] | None]") -> None:
        _current_span.reset(token)

    @classmethod
    def get_current_trace(cls) -> "Trace | None":
        return _current_trace.get()

    @classmethod
    def set_current_trace(
        cls, trace: "Trace | None"
    ) -> "contextvars.Token[Trace | None]":
        return _current_trace.set(trace)

    @classmethod
    def reset_current_trace(cls, token: "contextvars.Token[Trace | None]") -> None:
        _current_trace.reset(token)
