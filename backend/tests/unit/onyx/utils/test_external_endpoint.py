"""Unit tests for the generic external endpoint client."""

from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
from pydantic import BaseModel

from onyx.utils.external_endpoint import ExternalEndpointConfig
from onyx.utils.external_endpoint import post_json_to_endpoint

_CONFIG = ExternalEndpointConfig(
    endpoint_url="https://endpoint.example.com/x", timeout_seconds=5.0
)


class _StrictResponse(BaseModel):
    query: str


def _setup_client(mock_client_cls: MagicMock, response: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=response)
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)


def test_http_error_body_not_leaked_into_error_message() -> None:
    response = MagicMock()
    response.status_code = 500
    response.text = "SENSITIVE-DIAGNOSTIC-PAGE"
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=response
    )
    with patch("httpx.Client") as mock_client_cls:
        _setup_client(mock_client_cls, response)
        outcome, model = post_json_to_endpoint(
            config=_CONFIG, payload={}, response_type=_StrictResponse
        )

    assert not outcome.is_success
    assert model is None
    assert outcome.error_message == "External endpoint returned HTTP 500"
    assert "SENSITIVE-DIAGNOSTIC-PAGE" not in (outcome.error_message or "")


def test_fire_and_forget_accepts_empty_body_2xx() -> None:
    response = MagicMock()
    response.status_code = 204
    response.raise_for_status = MagicMock()
    response.json.side_effect = ValueError("no body")
    with patch("httpx.Client") as mock_client_cls:
        _setup_client(mock_client_cls, response)
        outcome, model = post_json_to_endpoint(config=_CONFIG, payload={})

    assert outcome.is_success
    assert outcome.reachability_signal is True
    assert model is None
    response.json.assert_not_called()


def test_typed_response_still_requires_json_object_body() -> None:
    import json as json_lib

    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.side_effect = json_lib.JSONDecodeError("no body", "", 0)
    with patch("httpx.Client") as mock_client_cls:
        _setup_client(mock_client_cls, response)
        outcome, model = post_json_to_endpoint(
            config=_CONFIG, payload={}, response_type=_StrictResponse
        )

    assert not outcome.is_success
    assert model is None
    assert "non-JSON" in (outcome.error_message or "")


def test_validation_error_input_values_not_leaked_into_error_message() -> None:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = {"query": {"secret": "SENSITIVE-RESPONSE-VALUE"}}
    with patch("httpx.Client") as mock_client_cls:
        _setup_client(mock_client_cls, response)
        outcome, model = post_json_to_endpoint(
            config=_CONFIG, payload={}, response_type=_StrictResponse
        )

    assert not outcome.is_success
    assert model is None
    assert "validation" in (outcome.error_message or "")
    # The offending field location is named, but not the response's values.
    assert "query" in (outcome.error_message or "")
    assert "SENSITIVE-RESPONSE-VALUE" not in (outcome.error_message or "")
