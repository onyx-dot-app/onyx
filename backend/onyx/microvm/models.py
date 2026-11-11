"""Data models of the Firecracker runtime (`SANDBOX_RUNTIME=firecracker`)."""

from pydantic import BaseModel, ConfigDict


class RegisteredNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    # host:port of the agent's mTLS listener.
    address: str
