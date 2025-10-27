import os
from typing import Any

import braintrust
from agents import set_trace_processors
from braintrust.wrappers.openai import BraintrustTracingProcessor
from braintrust_langchain import set_global_handler
from braintrust_langchain.callbacks import BraintrustCallbackHandler

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import BRAINTRUST_PROJECT
from onyx.utils.logger import setup_logger

logger = setup_logger()

MASKING_LENGTH = int(os.environ.get("BRAINTRUST_MASKING_LENGTH", "20000"))


def _truncate_str(s: str) -> str:
    tail = MASKING_LENGTH // 5
    head = MASKING_LENGTH - tail
    return f"{s[:head]}…{s[-tail:]}[TRUNCATED {len(s)} chars to {MASKING_LENGTH}]"


def _mask(data: Any) -> Any:
    """Mask data if it exceeds the maximum length threshold or contains private_key."""
    # Handle dictionaries recursively
    if isinstance(data, dict):
        masked_dict = {}
        for key, value in data.items():
            if isinstance(key, str) and "private_key" in key.lower():
                masked_dict[key] = "***REDACTED***"
            else:
                masked_dict[key] = _mask(value)
        return masked_dict

    # Handle lists recursively
    if isinstance(data, list):
        return [_mask(item) for item in data]

    # Handle strings
    if isinstance(data, str):
        # Mask the value if the key was "private_key" (handled in dict above)
        # Also check for private_key patterns in the string content
        if "private_key" in data.lower():
            return "***REDACTED***"
        if len(data) <= MASKING_LENGTH:
            return data
        return _truncate_str(data)

    # For other types, check length
    if len(str(data)) <= MASKING_LENGTH:
        return data
    return _truncate_str(str(data))


def setup_braintrust_if_creds_available() -> None:
    """Initialize Braintrust logger and set up global callback handler."""
    # Check if Braintrust API key is available
    if not BRAINTRUST_API_KEY:
        logger.info("Braintrust API key not provided, skipping Braintrust setup")
        return

    braintrust_logger = braintrust.init_logger(
        project=BRAINTRUST_PROJECT,
        api_key=BRAINTRUST_API_KEY,
    )
    braintrust.set_masking_function(_mask)
    handler = BraintrustCallbackHandler()
    set_global_handler(handler)
    set_trace_processors([BraintrustTracingProcessor(braintrust_logger)])
    logger.notice("Braintrust tracing initialized")
