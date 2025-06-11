import json
import os


IMAGE_GENERATION_OUTPUT_FORMAT = os.environ.get(
    "IMAGE_GENERATION_OUTPUT_FORMAT", "b64_json"
)

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
        from onyx.utils.logger import setup_logger

        logger = setup_logger()
        logger.error(
            "Failed to parse CUSTOM_TOOL_PASS_THROUGH_HEADERS, must be a valid JSON object"
        )
