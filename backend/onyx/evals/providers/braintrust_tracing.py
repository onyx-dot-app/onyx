import logging
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import Optional
from typing import Union
from uuid import UUID

from braintrust_langchain import set_global_handler
from braintrust_langchain.callbacks import BraintrustCallbackHandler
from braintrust_langchain.callbacks import LogEvent
from braintrust_langchain.callbacks import SpanAttributes
from braintrust_langchain.callbacks import SpanTypeAttribute

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import BRAINTRUST_PROJECT

_logger = logging.getLogger("braintrust_langchain")


def _truncate_to_chars(obj: Any, max_chars: int = 10_000) -> Any:
    """
    Truncate any object to first max_chars characters and note that it's been truncated.

    Args:
        obj: The object to potentially truncate
        max_chars: Maximum number of characters to keep

    Returns:
        Truncated object with truncation note if it was truncated
    """
    if obj is None:
        return obj

    obj_str = str(obj)

    if len(obj_str) <= max_chars:
        return obj

    truncated_str = obj_str[:max_chars]
    return f"{truncated_str}\n... [TRUNCATED: {len(obj_str):,} characters -> {max_chars:,} characters]"


class OnyxBraintrustCallbackHandler:
    """Wrapper around BraintrustCallbackHandler with input/output truncation functionality."""

    def __init__(
        self,
        braintrust_callback_handler: BraintrustCallbackHandler,
        max_chars: int = 10_000,
        truncate_data: bool = True,
    ) -> None:
        self._handler = braintrust_callback_handler
        self.max_chars = max_chars
        self.truncate_data = truncate_data

    def __getattr__(self, name: str) -> Any:
        """Delegate all other method calls to the wrapped handler."""
        return getattr(self._handler, name)

    def _end_span(
        self,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        input: Optional[Any] = None,
        output: Optional[Any] = None,
        expected: Optional[Any] = None,
        error: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        scores: Optional[Mapping[str, Union[int, float]]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        metrics: Optional[Mapping[str, Union[int, float]]] = None,
        dataset_record_id: Optional[str] = None,
    ) -> Any:
        # Truncate input and output if needed
        truncated_input = input
        truncated_output = output
        if self.truncate_data:
            if input is not None:
                truncated_input = _truncate_to_chars(input, self.max_chars)
            if output is not None:
                truncated_output = _truncate_to_chars(output, self.max_chars)

        # Call the wrapped handler's _end_span with truncated data
        return self._handler._end_span(
            run_id=run_id,
            parent_run_id=parent_run_id,
            input=truncated_input,
            output=truncated_output,
            expected=expected,
            error=error,
            tags=tags,
            scores=scores,
            metadata=metadata,
            metrics=metrics,
            dataset_record_id=dataset_record_id,
        )

    def _start_span(
        self,
        parent_run_id: Optional[UUID],
        run_id: UUID,
        name: Optional[str] = None,
        type: Optional[SpanTypeAttribute] = None,
        span_attributes: Optional[Union[SpanAttributes, Mapping[str, Any]]] = None,
        start_time: Optional[float] = None,
        set_current: Optional[bool] = None,
        parent: Optional[str] = None,
        event: Optional[LogEvent] = None,
    ) -> Any:
        # Truncate input and output in the event if needed
        truncated_event = event
        if self.truncate_data and event is not None:
            truncated_event = dict(event)  # Create a copy
            if "input" in truncated_event and truncated_event["input"] is not None:
                truncated_event["input"] = _truncate_to_chars(
                    truncated_event["input"], self.max_chars
                )
            if "output" in truncated_event and truncated_event["output"] is not None:
                truncated_event["output"] = _truncate_to_chars(
                    truncated_event["output"], self.max_chars
                )

        # Call the wrapped handler's _start_span with truncated event
        return self._handler._start_span(
            parent_run_id=parent_run_id,
            run_id=run_id,
            name=name,
            type=type,
            span_attributes=span_attributes,
            start_time=start_time,
            set_current=set_current,
            parent=parent,
            event=truncated_event,
        )


def setup_braintrust() -> None:
    """Initialize Braintrust logger and set up global callback handler."""
    import braintrust

    braintrust.init_logger(
        project=BRAINTRUST_PROJECT,
        api_key=BRAINTRUST_API_KEY,
    )

    handler = OnyxBraintrustCallbackHandler(BraintrustCallbackHandler())
    set_global_handler(handler)
