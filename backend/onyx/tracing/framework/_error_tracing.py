from typing import Any

from .create import get_current_span
from .spans import Span
from .spans import SpanError
from onyx.utils.logger import setup_logger


logger = setup_logger(__name__)


def attach_error_to_span(span: Span[Any], error: SpanError) -> None:
    span.set_error(error)


def attach_error_to_current_span(error: SpanError) -> None:
    span = get_current_span()
    if span:
        attach_error_to_span(span, error)
    else:
        logger.warning(f"No span to add error {error} to")
