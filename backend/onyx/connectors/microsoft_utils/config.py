from typing import Annotated, Any

from pydantic import BaseModel, Field

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


RU_PER_MINUTE_FIELD = "ru_per_minute"
# Microsoft's limit for one day is this many times its limit for one minute.
RU_PER_DAY_FACTOR = 960


class MicrosoftRateBudget(BaseModel):
    """The share of the app registration's rate limit that one connector can
    use. Microsoft limits the resource units (RU) of an app in a tenant by
    license tier. The setting is on the connector and not on the credential,
    because a credential change makes Onyx run the connector again."""

    # None: the connector shares the budget that the limiter learns from 429
    # answers with the other connectors on the app. It has no effect on
    # indexed data, so a change needs no re-index.
    ru_per_minute: Annotated[
        int | None, FieldPolicy(FieldClass.COSMETIC), Field(ge=1, le=1_000_000)
    ] = None


def configured_ru_per_minute(connector_specific_config: dict[str, Any]) -> int | None:
    """The connector's RU per minute, or None when it has none or the stored
    value is not a positive integer. The write path validates a numeric
    string such as "600" and stores it as sent, so the reader accepts one."""
    value = connector_specific_config.get(RU_PER_MINUTE_FIELD)
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value
