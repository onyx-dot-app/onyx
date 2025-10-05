import os
from typing import Any

import braintrust
from agents import set_trace_processors
from braintrust import init_logger
from braintrust.wrappers.openai import BraintrustTracingProcessor
from braintrust_langchain import set_global_handler
from braintrust_langchain.callbacks import BraintrustCallbackHandler

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import BRAINTRUST_PROJECT

MASKING_LENGTH = int(os.environ.get("BRAINTRUST_MASKING_LENGTH", "20000"))


def _truncate_str(s: str) -> str:
    tail = MASKING_LENGTH // 5
    head = MASKING_LENGTH - tail
    return f"{s[:head]}…{s[-tail:]}[TRUNCATED {len(s)} chars to {MASKING_LENGTH}]"


def _mask(data: Any) -> Any:
    """Mask data if it exceeds the maximum length threshold."""
    if len(str(data)) <= MASKING_LENGTH:
        return data
    return _truncate_str(str(data))


def setup_braintrust() -> None:
    """Initialize Braintrust logger and set up global callback handler."""

    braintrust.init_logger(
        project=BRAINTRUST_PROJECT,
        api_key=BRAINTRUST_API_KEY,
    )
    braintrust.set_masking_function(_mask)
    handler = BraintrustCallbackHandler()
    set_global_handler(handler)
    set_trace_processors([BraintrustTracingProcessor(init_logger(BRAINTRUST_PROJECT))])
