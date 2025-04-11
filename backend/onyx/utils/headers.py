from typing import TypedDict

from fastapi.datastructures import Headers

from onyx.configs.model_configs import LITELLM_EXTRA_HEADERS
from onyx.configs.model_configs import LITELLM_PASS_THROUGH_HEADERS
from onyx.configs.tool_configs import CUSTOM_TOOL_PASS_THROUGH_HEADERS
from onyx.utils.logger import setup_logger

logger = setup_logger()


class HeaderItemDict(TypedDict):
    key: str
    value: str


def clean_header_list(headers_to_clean: list[HeaderItemDict]) -> dict[str, str]:
    cleaned_headers: dict[str, str] = {}
    for item in headers_to_clean:
        key = item["key"]
        value = item["value"]
        if key in cleaned_headers:
            logger.warning(
                f"Duplicate header {key} found in custom headers, ignoring..."
            )
            continue
        cleaned_headers[key] = value
    return cleaned_headers


def header_dict_to_header_list(header_dict: dict[str, str]) -> list[HeaderItemDict]:
    return [{"key": key, "value": value} for key, value in header_dict.items()]


def header_list_to_header_dict(header_list: list[HeaderItemDict]) -> dict[str, str]:
    return {header["key"]: header["value"] for header in header_list}


def get_relevant_headers(
    headers: dict[str, str] | Headers, desired_headers: list[str] | None
) -> dict[str, str]:
    if not desired_headers:
        return {}

    pass_through_headers: dict[str, str] = {}
    for key in desired_headers:
        if key in headers:
            pass_through_headers[key] = headers[key]
        else:
            # fastapi makes all header keys lowercase, handling that here
            lowercase_key = key.lower()
            if lowercase_key in headers:
                pass_through_headers[lowercase_key] = headers[lowercase_key]

    return pass_through_headers


def get_litellm_additional_request_headers(
    headers: dict[str, str] | Headers,
) -> dict[str, str]:
    return get_relevant_headers(headers, LITELLM_PASS_THROUGH_HEADERS)


def build_llm_extra_headers(
    additional_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    extra_headers: dict[str, str] = {}
    if additional_headers:
        extra_headers.update(additional_headers)
    if LITELLM_EXTRA_HEADERS:
        extra_headers.update(LITELLM_EXTRA_HEADERS)
    return extra_headers


def get_custom_tool_additional_request_headers(
    headers: dict[str, str] | Headers,
) -> dict[str, str]:
    return get_relevant_headers(headers, CUSTOM_TOOL_PASS_THROUGH_HEADERS)
