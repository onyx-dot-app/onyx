"""The HubSpot SDK sends requests with no timeout unless one is passed per call,
so every gateway SDK call carries the shared timeout."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.hubspot.config import HubSpotObjectType
from onyx.connectors.hubspot.source_operations import HubSpotSourceOperations


def _gateway() -> tuple[HubSpotSourceOperations, MagicMock]:
    provider = MagicMock()
    provider.get_credentials.return_value = {"hubspot_access_token": "token"}
    gateway = HubSpotSourceOperations(credentials_provider=provider)
    client = MagicMock()
    gateway._client = client
    return gateway, client


def test_default_timeout_is_passed_to_the_sdk() -> None:
    gateway, _ = _gateway()
    sdk_fn = MagicMock(return_value="ok")

    result = gateway._sdk("op", sdk_fn, key="value")

    assert result == "ok"
    sdk_fn.assert_called_once_with(
        key="value", _request_timeout=REQUEST_TIMEOUT_SECONDS
    )


def test_explicit_timeout_is_preserved() -> None:
    gateway, _ = _gateway()
    sdk_fn = MagicMock(return_value="ok")

    gateway._sdk("op", sdk_fn, _request_timeout=5)

    sdk_fn.assert_called_once_with(_request_timeout=5)


def test_the_search_passes_the_timeout_to_the_sdk() -> None:
    gateway, client = _gateway()
    do_search = client.crm.tickets.search_api.do_search
    do_search.return_value.to_dict.return_value = {"results": [], "paging": None}

    gateway.search_records(
        variant=HubSpotObjectType.TICKETS,
        properties=["prop"],
        modified_after=datetime(2024, 1, 1, tzinfo=timezone.utc),
        modified_before=None,
    )

    assert do_search.call_args.kwargs["_request_timeout"] == REQUEST_TIMEOUT_SECONDS
