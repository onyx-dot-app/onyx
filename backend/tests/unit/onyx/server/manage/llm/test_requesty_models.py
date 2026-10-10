"""Tests for the Requesty model fetcher.

Requesty serves two public lists with the same fields: managed policies
(`/v1/models/managed`, bare ids) and the full catalog (`/v1/models`,
`vendor/model` ids). These tests verify that both are merged, non-chat and
unsafe ids are dropped, one failing list does not hide the other, and the key
is only sent to a Requesty router.
"""

from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.api import get_requesty_available_models
from onyx.server.manage.llm.models import (
    RequestyFinalModelResponse,
    RequestyModelsRequest,
)

_MANAGED = {
    "object": "list",
    "data": [
        {
            "id": "claude-haiku-4-5",
            "api": "chat",
            "context_window": 200000,
            "supports_vision": True,
            "supports_reasoning": True,
        },
    ],
}

_CATALOG = {
    "object": "list",
    "data": [
        {
            "id": "openai/gpt-4o-mini",
            "api": "chat",
            "context_window": 128000,
            "supports_vision": True,
            "supports_reasoning": False,
        },
        # Duplicate of the entry above, skipped.
        {"id": "openai/gpt-4o-mini", "api": "chat"},
        {"id": "openai/text-embedding-3-small", "api": "embedding"},
        {"id": "evil/\x1b[31mmodel", "api": "chat"},
        {"id": "", "api": "chat"},
    ],
}


def _fetch(
    responses: dict[str, Any],
    api_base: str | None = None,
) -> tuple[list[RequestyFinalModelResponse], list[str]]:
    """`responses` maps a URL suffix to a payload, or to an OnyxError to raise."""
    urls: list[str] = []

    def fake_response(url: str, **_: Any) -> dict:
        urls.append(url)
        for suffix, payload in responses.items():
            if url.endswith(suffix):
                if isinstance(payload, OnyxError):
                    raise payload
                return payload
        raise AssertionError(f"unexpected url {url}")

    with patch(
        "onyx.server.manage.llm.api._get_openai_compatible_models_response",
        side_effect=fake_response,
    ):
        models = get_requesty_available_models(
            request=RequestyModelsRequest(api_base=api_base, provider_id=None),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
    return models, urls


def _both() -> dict[str, Any]:
    return {"/models/managed": _MANAGED, "/v1/models": _CATALOG}


def test_managed_and_catalog_models_are_merged_and_sorted() -> None:
    models, urls = _fetch(_both())
    assert [m.name for m in models] == ["claude-haiku-4-5", "openai/gpt-4o-mini"]
    assert urls == [
        "https://router.requesty.ai/v1/models/managed",
        "https://router.requesty.ai/v1/models",
    ]


def test_catalog_metadata_maps_onto_the_model_config() -> None:
    models, _ = _fetch(_both())
    haiku = next(m for m in models if m.name == "claude-haiku-4-5")
    assert haiku.display_name == "claude-haiku-4-5"
    assert haiku.max_input_tokens == 200000
    assert haiku.supports_image_input is True
    assert haiku.supports_reasoning is True


def test_missing_capability_fields_default_to_false() -> None:
    models, _ = _fetch(
        {"/models/managed": {"data": [{"id": "gpt-5.4-mini"}]}, "/v1/models": {}}
    )
    assert models[0].max_input_tokens is None
    assert models[0].supports_image_input is False
    assert models[0].supports_reasoning is False


def test_regional_base_without_v1_is_normalized() -> None:
    _, urls = _fetch(_both(), api_base="https://router.eu.requesty.ai/")
    assert urls[0] == "https://router.eu.requesty.ai/v1/models/managed"


def test_one_failing_list_still_returns_the_other() -> None:
    error = OnyxError(OnyxErrorCode.BAD_GATEWAY, "boom")
    models, _ = _fetch({"/models/managed": error, "/v1/models": _CATALOG})
    assert [m.name for m in models] == ["openai/gpt-4o-mini"]


def test_both_lists_failing_raises() -> None:
    error = OnyxError(OnyxErrorCode.BAD_GATEWAY, "boom")
    with pytest.raises(OnyxError):
        _fetch({"/models/managed": error, "/v1/models": error})


def test_empty_lists_raise() -> None:
    with pytest.raises(OnyxError):
        _fetch({"/models/managed": {"data": []}, "/v1/models": {"data": []}})


@pytest.mark.parametrize(
    "api_base",
    [
        "http://router.requesty.ai/v1",
        "https://router.requesty.ai.example.com/v1",
        "https://evil.example.com/router.requesty.ai/v1",
        "https://notrouter.requesty.ai/v1",
    ],
)
def test_non_requesty_base_is_rejected_before_any_request(api_base: str) -> None:
    with patch(
        "onyx.server.manage.llm.api._get_openai_compatible_models_response"
    ) as mock_fetch:
        with pytest.raises(OnyxError):
            get_requesty_available_models(
                request=RequestyModelsRequest(api_base=api_base, api_key="key"),
                _=cast(User, None),
                db_session=cast(Session, None),
            )
    mock_fetch.assert_not_called()
