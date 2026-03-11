"""Inverse mapping from user-facing Microsoft host URLs to the SDK's AzureEnvironment.

The office365 library's GraphClient requires an ``AzureEnvironment`` string
(e.g. ``"Global"``, ``"GCC High"``) to route requests to the correct national
cloud.  Our connectors instead expose free-text ``authority_host`` and
``graph_api_host`` fields so the frontend doesn't need to know about SDK
internals.

This module bridges the gap: given the two host URLs the user configured, it
resolves the matching ``AzureEnvironment`` value (and the implied SharePoint
domain suffix) so callers can pass ``environment=…`` to ``GraphClient``.
"""

from office365.graph_client import AzureEnvironment  # type: ignore[import-untyped]
from pydantic import BaseModel

from onyx.connectors.exceptions import ConnectorValidationError


class MicrosoftGraphEnvironment(BaseModel):
    """One row of the inverse mapping."""

    environment: str
    graph_host: str
    authority_host: str
    sharepoint_domain_suffix: str


_ENVIRONMENTS: list[MicrosoftGraphEnvironment] = [
    MicrosoftGraphEnvironment(
        environment=AzureEnvironment.Global,
        graph_host="https://graph.microsoft.com",
        authority_host="https://login.microsoftonline.com",
        sharepoint_domain_suffix="sharepoint.com",
    ),
    MicrosoftGraphEnvironment(
        environment=AzureEnvironment.USGovernmentHigh,
        graph_host="https://graph.microsoft.us",
        authority_host="https://login.microsoftonline.us",
        sharepoint_domain_suffix="sharepoint.us",
    ),
    MicrosoftGraphEnvironment(
        environment=AzureEnvironment.USGovernmentDoD,
        graph_host="https://dod-graph.microsoft.us",
        authority_host="https://login.microsoftonline.us",
        sharepoint_domain_suffix="sharepoint.us",
    ),
    MicrosoftGraphEnvironment(
        environment=AzureEnvironment.China,
        graph_host="https://microsoftgraph.chinacloudapi.cn",
        authority_host="https://login.chinacloudapi.cn",
        sharepoint_domain_suffix="sharepoint.cn",
    ),
    MicrosoftGraphEnvironment(
        environment=AzureEnvironment.Germany,
        graph_host="https://graph.microsoft.de",
        authority_host="https://login.microsoftonline.de",
        sharepoint_domain_suffix="sharepoint.de",
    ),
]

_GRAPH_HOST_INDEX: dict[str, MicrosoftGraphEnvironment] = {
    env.graph_host: env for env in _ENVIRONMENTS
}


def resolve_microsoft_environment(
    graph_api_host: str,
    authority_host: str,
) -> MicrosoftGraphEnvironment:
    """Return the ``MicrosoftGraphEnvironment`` that matches the supplied hosts.

    Raises ``ConnectorValidationError`` when the combination is unknown or
    internally inconsistent (e.g. a GCC-High graph host paired with a
    commercial authority host).
    """
    graph_api_host = graph_api_host.rstrip("/")
    authority_host = authority_host.rstrip("/")

    env = _GRAPH_HOST_INDEX.get(graph_api_host)
    if env is None:
        known = ", ".join(sorted(_GRAPH_HOST_INDEX))
        raise ConnectorValidationError(
            f"Unsupported Microsoft Graph API host '{graph_api_host}'. "
            f"Recognised hosts: {known}"
        )

    if env.authority_host != authority_host:
        raise ConnectorValidationError(
            f"Authority host '{authority_host}' is inconsistent with "
            f"graph API host '{graph_api_host}'. "
            f"Expected authority host '{env.authority_host}' "
            f"for the {env.environment} environment."
        )

    return env
