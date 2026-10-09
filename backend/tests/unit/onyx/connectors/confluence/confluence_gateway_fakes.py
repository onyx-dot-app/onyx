"""Builds a Confluence gateway around a fake transport client for unit tests."""

from typing import Any
from unittest import mock

from onyx.connectors.confluence.source_operations import ConfluenceSourceOperations
from onyx.connectors.interfaces import CredentialsProviderInterface


def gateway_with_client(
    client: Any,
    *,
    wiki_base: str = "https://example.atlassian.net/wiki",
    is_cloud: bool = False,
) -> ConfluenceSourceOperations:
    """Returns a gateway whose main and fast clients are both ``client``."""
    gateway = ConfluenceSourceOperations(
        credentials_provider=mock.Mock(spec=CredentialsProviderInterface),
        connector_specific_config={"wiki_base": wiki_base, "is_cloud": is_cloud},
    )
    gateway._cached_client = client
    gateway._cached_fast_client = client
    return gateway
