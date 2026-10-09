from onyx.connectors.connector_config import CredentialBinding

# Commercial-cloud hosts the Microsoft connector forms start from.
DEFAULT_AUTHORITY_HOST = "https://login.microsoftonline.com"
DEFAULT_GRAPH_API_HOST = "https://graph.microsoft.com"
DEFAULT_SHAREPOINT_DOMAIN_SUFFIX = "sharepoint.com"


class MicrosoftCloudBinding(CredentialBinding):
    """The national cloud the app registration lives in."""

    authority_host: str = DEFAULT_AUTHORITY_HOST
    graph_api_host: str = DEFAULT_GRAPH_API_HOST
