from fastapi.datastructures import Headers

from danswer.configs.model_configs import LITELLM_EXTRA_HEADERS
from danswer.configs.model_configs import LITELLM_PASS_THROUGH_HEADERS


def get_litellm_additional_request_headers(
    headers: dict[str, str] | Headers
) -> dict[str, str]:
    if not LITELLM_PASS_THROUGH_HEADERS:
        return {}

    pass_through_headers: dict[str, str] = {}
    for key in LITELLM_PASS_THROUGH_HEADERS:
        if key in headers:
            pass_through_headers[key] = headers[key]
        else:
            # fastapi makes all header keys lowercase, handling that here
            lowercase_key = key.lower()
            if lowercase_key in headers:
                pass_through_headers[lowercase_key] = headers[lowercase_key]

    return pass_through_headers


def build_llm_extra_headers(
    additional_headers: dict[str, str] | None = None
) -> dict[str, str]:
    extra_headers: dict[str, str] = {}
    if additional_headers:
        extra_headers.update(additional_headers)
    if LITELLM_EXTRA_HEADERS:
        extra_headers.update(LITELLM_EXTRA_HEADERS)
    return extra_headers
