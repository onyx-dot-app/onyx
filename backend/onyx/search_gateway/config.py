from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_TAVILY_API_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_CHANNEL = "tavily"


@dataclass(frozen=True)
class SearchGatewayConfig:
    gateway_api_key: str | None
    tavily_api_key: str | None
    tavily_api_url: str = DEFAULT_TAVILY_API_URL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    default_channel: str = DEFAULT_CHANNEL


def load_search_gateway_config_from_env() -> SearchGatewayConfig:
    return SearchGatewayConfig(
        gateway_api_key=_clean_optional_env("GLOMI_SEARCH_GATEWAY_API_KEY"),
        tavily_api_key=_clean_optional_env("TAVILY_API_KEY"),
        tavily_api_url=(
            _clean_optional_env("GLOMI_SEARCH_GATEWAY_TAVILY_API_URL")
            or DEFAULT_TAVILY_API_URL
        ),
        timeout_seconds=_positive_int_env(
            "GLOMI_SEARCH_GATEWAY_TIMEOUT_SECONDS",
            default=DEFAULT_TIMEOUT_SECONDS,
        ),
        default_channel=(
            _clean_optional_env("GLOMI_SEARCH_GATEWAY_DEFAULT_CHANNEL")
            or DEFAULT_CHANNEL
        ).lower(),
    )


def _clean_optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _positive_int_env(name: str, *, default: int) -> int:
    value = _clean_optional_env(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
