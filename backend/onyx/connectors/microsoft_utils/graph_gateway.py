from typing import Any
from urllib.parse import quote

import requests
from pydantic import BaseModel, ConfigDict

from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthContext,
    acquire_graph_token_response,
    build_graph_auth_context,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.microsoft_utils.graph_errors import (
    microsoft_error_from_exception,
)


class MicrosoftGraphAuthConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_id: str | None
    directory_id: str | None
    authority_host: str
    auth_method: str | None = None
    client_secret: str | None = None
    private_key_b64: str | None = None
    certificate_password: str | None = None


def build_graph_user_url(graph_api_base: str, identifier: str) -> str:
    if identifier.startswith("$"):
        literal = quote(identifier.replace("'", "''"), safe="@$'")
        return f"{graph_api_base}/users('{literal}')"
    return f"{graph_api_base}/users/{quote(identifier, safe='@')}"


class MicrosoftGraphGateway:
    def __init__(
        self,
        *,
        auth_config: MicrosoftGraphAuthConfig,
        graph_api_host: str,
        graph_api_version: str,
    ) -> None:
        self.auth_config = auth_config
        self.graph_api_host = graph_api_host.rstrip("/")
        self.graph_api_base = f"{self.graph_api_host}/{graph_api_version}"
        self._auth_context: MicrosoftAuthContext | None = None
        self._client: GraphApiClient | None = None

    @property
    def auth_context(self) -> MicrosoftAuthContext:
        if self._auth_context is None:
            config = self.auth_config
            self._auth_context = build_graph_auth_context(
                client_id=config.client_id,
                directory_id=config.directory_id,
                authority_host=config.authority_host,
                auth_method_value=config.auth_method,
                client_secret=config.client_secret,
                private_key_b64=config.private_key_b64,
                certificate_password=config.certificate_password,
            )
        return self._auth_context

    def token_response(self) -> dict[str, Any]:
        return acquire_graph_token_response(self.auth_context, self.graph_api_host)

    def access_token(self) -> str:
        return str(self.token_response()["access_token"])

    @property
    def client(self) -> GraphApiClient:
        if self._client is None:
            self._client = GraphApiClient(self.access_token, self.graph_api_base)
        return self._client

    def get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            return self.client.get_json(url, params, headers)
        except (requests.RequestException, ValueError) as error:
            raise microsoft_error_from_exception(error) from error
