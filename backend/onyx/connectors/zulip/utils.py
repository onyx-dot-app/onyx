import time
from collections.abc import Callable
from typing import Any, Dict, Optional
from urllib.parse import quote

from onyx.connectors.cross_connector_utils.server_wait import bound_server_wait
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


class ZulipAPIError(Exception):
    def __init__(self, code: Any = None, msg: str | None = None) -> None:
        self.code = code
        self.msg = msg

    def __str__(self) -> str:
        return (
            f"Error occurred during Zulip API call: {self.msg}" + ""
            if self.code is None
            else f" ({self.code})"
        )


class ZulipHTTPError(ZulipAPIError):
    def __init__(self, msg: str | None = None, status_code: Any = None) -> None:
        super().__init__(code=None, msg=msg)
        self.status_code = status_code

    def __str__(self) -> str:
        return f"HTTP error {self.status_code} occurred during Zulip API call"


# Cloud only; self-hosted retries until the server stops rate limiting.
_MAX_RATE_LIMIT_RETRIES_MULTI_TENANT = 5


def __call_with_retry(fun: Callable, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    retries = 0
    while True:
        result = fun(*args, **kwargs)
        if not (
            result.get("result") == "error" and result.get("code") == "RATE_LIMIT_HIT"
        ):
            return result
        if MULTI_TENANT and retries >= _MAX_RATE_LIMIT_RETRIES_MULTI_TENANT:
            # __raise_if_error raises the rate-limit error.
            return result
        retries += 1
        retry_after = bound_server_wait(float(result["retry-after"]) + 1, "zulip")
        logger.warning("Rate limit hit, retrying after %s seconds", retry_after)
        time.sleep(retry_after)


def __raise_if_error(response: dict[str, Any]) -> None:
    if response.get("result") == "error":
        raise ZulipAPIError(
            code=response.get("code"),
            msg=response.get("msg"),
        )
    elif response.get("result") == "http-error":
        raise ZulipHTTPError(
            msg=response.get("msg"), status_code=response.get("status_code")
        )


def call_api(fun: Callable, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    response = __call_with_retry(fun, *args, **kwargs)
    __raise_if_error(response)
    return response


def build_search_narrow(
    *,
    stream: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = 100,
    content: Optional[str] = None,
    apply_md: bool = False,
    anchor: str = "newest",
) -> Dict[str, Any]:
    narrow_filters = []

    if stream:
        narrow_filters.append({"operator": "stream", "operand": stream})

    if topic:
        narrow_filters.append({"operator": "topic", "operand": topic})

    if content:
        narrow_filters.append({"operator": "has", "operand": content})

    if not stream and not topic and not content:
        narrow_filters.append({"operator": "streams", "operand": "public"})

    narrow = {
        "anchor": anchor,
        "num_before": limit,
        "num_after": 0,
        "narrow": narrow_filters,
    }
    narrow["apply_markdown"] = apply_md

    return narrow


def encode_zulip_narrow_operand(value: str) -> str:
    # like https://github.com/zulip/zulip/blob/1577662a6/static/js/hash_util.js#L18-L25
    # safe characters necessary to make Python match Javascript's escaping behaviour,
    # see: https://stackoverflow.com/a/74439601
    return quote(value, safe="!~*'()").replace(".", "%2E").replace("%", ".")
