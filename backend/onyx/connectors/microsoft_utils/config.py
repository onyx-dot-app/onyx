from typing import Annotated

from onyx.connectors.connector_config import CredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy

# Commercial-cloud hosts the Microsoft connector forms start from.
DEFAULT_AUTHORITY_HOST = "https://login.microsoftonline.com"
DEFAULT_GRAPH_API_HOST = "https://graph.microsoft.com"
DEFAULT_SHAREPOINT_DOMAIN_SUFFIX = "sharepoint.com"

# The hosts select the national cloud: a Graph object id resolves only in it.
_NATIONAL_CLOUD = FieldPolicy(FieldClass.IDENTITY)


class MicrosoftCloudBinding(CredentialBinding):
    """The national cloud the app registration lives in."""

    authority_host: Annotated[str, _NATIONAL_CLOUD] = DEFAULT_AUTHORITY_HOST
    graph_api_host: Annotated[str, _NATIONAL_CLOUD] = DEFAULT_GRAPH_API_HOST
