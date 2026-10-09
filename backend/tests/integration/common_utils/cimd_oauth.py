from pathlib import Path

from pydantic import BaseModel


class OAuthHttpsEndpoint(BaseModel):
    origin: str
    ca_file: Path


class CimdOAuthTestServices(BaseModel):
    mcp_server_url: str
    oidc_issuer: str
    client_metadata_url: str


class MockOidcStatus(BaseModel):
    client_metadata_fetch_count: int
    registration_request_count: int
    last_client_id: str | None
