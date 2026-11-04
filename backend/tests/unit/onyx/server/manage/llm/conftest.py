"""The LLM admin tests use placeholder hosts that never resolve, so the api_base
SSRF guard keeps its structural checks but skips DNS here."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from onyx.server.manage.llm import api


@pytest.fixture(autouse=True)
def skip_api_base_dns() -> Iterator[None]:
    real_validate = api.validate_outbound_http_url

    def _validate_without_dns(url: str, **kwargs: Any) -> str:
        return real_validate(url, **{**kwargs, "resolve_dns": False})

    with patch.object(api, "validate_outbound_http_url", _validate_without_dns):
        yield
