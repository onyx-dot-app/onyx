from typing import Any

import braintrust
from braintrust_langchain import set_global_handler
from braintrust_langchain.callbacks import BraintrustCallbackHandler

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import BRAINTRUST_PROJECT


def _truncate_str(s: str, head=800, tail=200) -> str:
    if len(s) <= head + tail:
        return s
    return f"{s[:head]}…[TRUNCATED {len(s) - head - tail} chars]…{s[-tail:]}"


def _mask(data: Any) -> Any:
    data_str = str(data)

    if len(data_str) > 10_000:
        return f"{data_str[:10_000]}…[TRUNCATED {len(data_str)} to 10,000 chars]…"
    if isinstance(data, str):
        return _truncate_str(data)
    if isinstance(data, list):
        return [_mask(x) for x in data]
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            # Be extra strict for common LLM fields
            if k in {"content", "prompt", "completion"} and isinstance(v, str):
                out[k] = _truncate_str(v)
            else:
                out[k] = _mask(v)
        return out
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
