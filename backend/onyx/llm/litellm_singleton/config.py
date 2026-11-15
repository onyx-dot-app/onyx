import threading

import litellm

from onyx.utils.logger import remove_litellm_native_log_handlers, setup_logger

logger = setup_logger()


def configure_litellm_settings() -> None:
    # If a user configures a different model and it doesn't support all the same
    # parameters like frequency and presence, just ignore them
    litellm.drop_params = True
    litellm.telemetry = False  # ty: ignore[invalid-assignment]
    litellm.modify_params = True
    litellm.add_function_to_prompt = False
    litellm.suppress_debug_info = True
    # LiteLLM submits a threadpool task per streamed chunk that spins up a new
    # asyncio event loop to run success callbacks and cache writes. Onyx
    # registers neither (tracing and cost accounting are our own), so skip it.
    # Removing it cuts ~60% of the CPU spent consuming a stream.
    litellm.disable_streaming_logging = True
    # LiteLLM records must flow only through the app logging pipeline, not also
    # through the stream handler LiteLLM attaches at import.
    remove_litellm_native_log_handlers()


_INIT_LOCK = threading.Lock()
_initialized = False


def initialize_litellm() -> None:
    """Configure the process-wide litellm module. Safe to call from any thread."""
    global _initialized
    if _initialized:
        return
    with _INIT_LOCK:
        if _initialized:
            return
        configure_litellm_settings()
        _initialized = True
