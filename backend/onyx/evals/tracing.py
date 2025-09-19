from typing import Any

import braintrust
from braintrust_langchain import set_global_handler
from braintrust_langchain.callbacks import BraintrustCallbackHandler

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import BRAINTRUST_PROJECT


def _truncate_str(s: str, head: int = 800, tail: int = 200) -> str:
    if len(s) <= head + tail:
        return s
    return f"{s[:head]}…{s[-tail:]}[TRUNCATED {len(s)} chars to 10,000]"


def _mask(data: Any) -> Any:
    data_str = str(data)
    if len(data_str) > 10_000:
        return _truncate_str(data_str)
    return data


def setup_braintrust() -> None:
    """Initialize Braintrust logger and set up global callback handler."""

    braintrust.init_logger(
        project=BRAINTRUST_PROJECT,
        api_key=BRAINTRUST_API_KEY,
    )
    braintrust.set_masking_function(_mask)
    handler = BraintrustCallbackHandler()
    set_global_handler(handler)
