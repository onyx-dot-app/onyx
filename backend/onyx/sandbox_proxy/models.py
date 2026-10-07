"""Configuration models for the sandbox egress proxy."""

import ipaddress

from pydantic import BaseModel, ConfigDict

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class DestinationPolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_host: str | None
    api_port: int | None
    internal_networks: tuple[IPNetwork, ...]
