import httpx
from cohere.core.api_error import ApiError
from voyageai.error import RateLimitError as VoyageRateLimitError

from onyx.natural_language_processing.exceptions import ModelServerRateLimitError


def is_rate_limit_error(error: BaseException) -> bool:
    """Whether a provider refused the request because of its rate limit or quota."""
    import openai
    from google.genai import errors as genai_errors

    # litellm's RateLimitError subclasses openai's.
    if isinstance(
        error,
        (
            ModelServerRateLimitError,
            openai.RateLimitError,
            VoyageRateLimitError,
        ),
    ):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 429
    if isinstance(error, ApiError):
        return error.status_code == 429
    if isinstance(error, genai_errors.APIError):
        return error.code == 429
    return False
