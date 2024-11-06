import json
import os


# if specified, will pass through request headers to the call to API calls made by custom tools
CUSTOM_TOOL_PASS_THROUGH_HEADERS: list[str] | None = None
_CUSTOM_TOOL_PASS_THROUGH_HEADERS_RAW = os.environ.get(
    "CUSTOM_TOOL_PASS_THROUGH_HEADERS"
)
if _CUSTOM_TOOL_PASS_THROUGH_HEADERS_RAW:
    try:
        CUSTOM_TOOL_PASS_THROUGH_HEADERS = json.loads(
            _CUSTOM_TOOL_PASS_THROUGH_HEADERS_RAW
        )
    except Exception:
        # need to import here to avoid circular imports
        from danswer.utils.logger import setup_logger

        logger = setup_logger()
        logger.error(
            "Failed to parse CUSTOM_TOOL_PASS_THROUGH_HEADERS, must be a valid JSON object"
        )
