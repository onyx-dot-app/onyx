"""What the admin view reports as receiving must match what the webhook route
accepts: an unsigned source refuses deliveries once several pairs exist."""

from collections.abc import Mapping
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import WebhookRequest, WebhookSourceSpec
from onyx.connectors.event_models import EventParseResult
from onyx.server.documents import connector as connector_api


def _parse(request: WebhookRequest) -> EventParseResult:  # noqa: ARG001
    return EventParseResult()


def _verify(request: WebhookRequest, secrets: Mapping[str, str]) -> None:  # noqa: ARG001
    return None


SIGNED = WebhookSourceSpec(
    source=DocumentSource.MOCK_CONNECTOR, slug="s", parser=_parse, verifier=_verify
)
UNSIGNED = WebhookSourceSpec(
    source=DocumentSource.MOCK_CONNECTOR,
    slug="u",
    parser=_parse,
    verifier=None,
    allow_unsigned=True,
)


@pytest.mark.parametrize(
    ("spec", "active_pairs", "receiving"),
    [
        (SIGNED, 0, False),
        (SIGNED, 1, True),
        (SIGNED, 2, True),
        (UNSIGNED, 0, False),
        (UNSIGNED, 1, True),
        (UNSIGNED, 2, False),
    ],
)
def test_receiving_matches_what_the_route_accepts(
    spec: WebhookSourceSpec, active_pairs: int, receiving: bool
) -> None:
    with (
        patch.object(connector_api, "load_event_sources"),
        patch.object(connector_api, "registered_webhook_sources", return_value=[spec]),
        patch.object(
            connector_api,
            "get_active_event_cc_pairs",
            return_value=[MagicMock() for _ in range(active_pairs)],
        ),
    ):
        snapshots = connector_api.get_event_sources(MagicMock(), MagicMock())

    assert [snapshot.receiving for snapshot in snapshots] == [receiving]
