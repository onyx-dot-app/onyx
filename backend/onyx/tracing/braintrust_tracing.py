import os
import re
from typing import Any

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import BRAINTRUST_PROJECT
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Set very loosely because some tool call results may be very long.
# Ideally we don't pass those to the LLM but it's fine if we want to trace them in full.
MASKING_LENGTH = int(os.environ.get("BRAINTRUST_MASKING_LENGTH", "500000"))


def _truncate_str(s: str) -> str:
    tail = MASKING_LENGTH // 5
    head = MASKING_LENGTH - tail
    return f"{s[:head]}…{s[-tail:]}[TRUNCATED {len(s)} chars to {MASKING_LENGTH}]"


def _mask(data: Any) -> Any:
    """Mask data if it exceeds the maximum length threshold or contains sensitive information."""
    # Handle dictionaries recursively
    if isinstance(data, dict):
        masked_dict = {}
        for key, value in data.items():
            # Mask private keys and authorization headers
            if isinstance(key, str) and (
                "private_key" in key.lower() or "authorization" in key.lower()
            ):
                masked_dict[key] = "***REDACTED***"
            else:
                masked_dict[key] = _mask(value)
        return masked_dict

    # Handle lists recursively
    if isinstance(data, list):
        return [_mask(item) for item in data]

    # Handle strings
    if isinstance(data, str):
        # Mask private_key patterns
        if "private_key" in data.lower():
            return "***REDACTED***"

        # Mask Authorization: Bearer tokens
        # Pattern matches "Authorization: Bearer <token>" or "authorization: bearer <token>"
        if re.search(r"authorization:\s*bearer\s+\S+", data, re.IGNORECASE):
            data = re.sub(
                r"(authorization:\s*bearer\s+)\S+",
                r"\1***REDACTED***",
                data,
                flags=re.IGNORECASE,
            )

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

    # Lazy imports to avoid loading braintrust when not needed
    import braintrust

    from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor
    from onyx.tracing.framework import set_trace_processors

    braintrust_logger = braintrust.init_logger(
        project=BRAINTRUST_PROJECT,
        api_key=BRAINTRUST_API_KEY,
    )
    braintrust.set_masking_function(_mask)
    set_trace_processors([BraintrustTracingProcessor(braintrust_logger)])
    logger.notice("Braintrust tracing initialized")
