from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class OutboundFieldSource(StrEnum):
    CONFIG = "config"
    CREDENTIAL = "credential"


class OutboundUrlField(BaseModel):
    """A config or credential value the connector sends requests to."""

    model_config = ConfigDict(frozen=True)

    source: OutboundFieldSource
    key: str


class OutboundSubdomainField(BaseModel):
    """A value the connector puts in ``https://{value}.{vendor_domain}``. It
    may also be the full vendor URL. The connector receives only the label."""

    model_config = ConfigDict(frozen=True)

    source: OutboundFieldSource
    key: str
    vendor_domain: str


OutboundField = OutboundUrlField | OutboundSubdomainField
