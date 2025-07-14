from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from onyx.configs.constants import FederatedConnectorSource


class FederatedConnectorCredentials(BaseModel):
    """Credentials for federated connector"""

    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None


class FederatedConnectorRequest(BaseModel):
    source: FederatedConnectorSource
    credentials: FederatedConnectorCredentials


class FederatedConnectorResponse(BaseModel):
    id: int
    source: FederatedConnectorSource


class AuthorizeUrlResponse(BaseModel):
    authorize_url: str


class OAuthCallbackResult(BaseModel):
    access_token: str | None = None
    expires_at: datetime | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    scope: str | None = None
    source: FederatedConnectorSource | None = None


class FederatedConnectorStatus(BaseModel):
    id: int
    source: FederatedConnectorSource
    name: str


class UserOAuthStatus(BaseModel):
    """OAuth status for a specific user and federated connector"""

    federated_connector_id: int
    source: FederatedConnectorSource
    name: str
    has_oauth_token: bool
    oauth_token_expires_at: datetime | None = None
    authorize_url: str | None = None


class FederatedConnectorDetail(BaseModel):
    id: int
    source: FederatedConnectorSource
    name: str
    credentials: FederatedConnectorCredentials
    oauth_token_exists: bool
    oauth_token_expires_at: datetime | None = None
    document_sets: list[dict[str, Any]] = Field(default_factory=list)


class FederatedConnectorSummary(BaseModel):
    """Simplified federated connector information with just essential data"""

    id: int
    name: str
    source: FederatedConnectorSource
    entities: dict[str, Any]

    @classmethod
    def from_federated_connector_detail(
        cls, detail: FederatedConnectorDetail, entities: dict[str, Any]
    ) -> "FederatedConnectorSummary":
        return cls(
            id=detail.id,
            name=detail.name,
            source=detail.source,
            entities=entities,
        )


class FederatedConnectorUpdateRequest(BaseModel):
    credentials: FederatedConnectorCredentials | None = None


class EntitySpecResponse(BaseModel):
    """Response for entity specification"""

    entities: dict[str, Any]


class CredentialSchemaResponse(BaseModel):
    """Response for credential schema specification"""

    credentials: dict[str, Any]
