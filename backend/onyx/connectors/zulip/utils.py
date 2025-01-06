import time
from collections.abc import Callable
from typing import Any
from typing import Dict
from typing import Optional
from urllib.parse import quote

from onyx.utils.logger import setup_logger

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


def __call_with_retry(fun: Callable, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    result = fun(*args, **kwargs)
    if result.get("result") == "error":
        if result.get("code") == "RATE_LIMIT_HIT":
            retry_after = float(result["retry-after"]) + 1
            logger.warn(f"Rate limit hit, retrying after {retry_after} seconds")
            time.sleep(retry_after)
            return __call_with_retry(fun, *args)
    return result


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
