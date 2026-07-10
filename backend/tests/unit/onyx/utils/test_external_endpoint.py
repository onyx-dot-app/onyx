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
