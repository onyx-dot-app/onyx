"""What every Teams content source reads the tenant through: the app's
credential, the Graph client built from it, and the endpoints of its cloud."""

import threading
from collections.abc import Callable
from typing import Any

import msal
from office365.graph_client import GraphClient

from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthMethod,
    acquire_graph_token,
    build_msal_app,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.microsoft_utils.graph_env import resolve_microsoft_environment
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.teams.utils import UserDirectory

CREDENTIAL_AUTH_METHOD = "authentication_method"
CREDENTIAL_PRIVATE_KEY = "teams_private_key"
CREDENTIAL_CERTIFICATE_PASSWORD = "teams_certificate_password"


class TeamsSession:
    def __init__(self, graph_api_host: str, authority_host: str) -> None:
        self.graph_client: GraphClient | None = None
        self.msal_app: msal.ConfidentialClientApplication | None = None
        self._acquire_token: Callable[[], dict[str, Any]] | None = None
        self._auth_method = MicrosoftAuthMethod.CLIENT_SECRET
        # Granted by the factory from the image analysis setting.
        self.allow_images = False
        self._user_directory: UserDirectory | None = None
        self._directory_lock = threading.Lock()

        resolved_env = resolve_microsoft_environment(graph_api_host, authority_host)
        self._azure_environment = resolved_env.environment
        self.authority_host = resolved_env.authority_host
        self.graph_api_host = resolved_env.graph_host
        self.sharepoint_domain_suffix = resolved_env.sharepoint_domain_suffix

    def open(self, credentials: dict[str, Any]) -> None:
        self._auth_method = MicrosoftAuthMethod.parse(
            credentials.get(CREDENTIAL_AUTH_METHOD)
        )
        self.msal_app = build_msal_app(
            client_id=credentials["teams_client_id"],
            directory_id=credentials["teams_directory_id"],
            authority_host=self.authority_host,
            auth_method=self._auth_method,
            # A client-secret credential must carry its secret. The certificate
            # method carries a key instead, so neither key is always present.
            client_secret=(
                credentials["teams_client_secret"]
                if self._auth_method is MicrosoftAuthMethod.CLIENT_SECRET
                else credentials.get("teams_client_secret")
            ),
            private_key_b64=credentials.get(CREDENTIAL_PRIVATE_KEY),
            certificate_password=credentials.get(CREDENTIAL_CERTIFICATE_PASSWORD),
        ).app

        def _acquire_token_func() -> dict[str, Any]:
            """
            Acquire token via MSAL
            """
            if self.msal_app is None:
                raise RuntimeError("MSAL app is not initialized")

            token = acquire_graph_token(self.msal_app, self.graph_api_host)

            if not isinstance(token, dict):
                raise RuntimeError("`token` instance must be of type dict")

            return token

        self.graph_client = GraphClient(
            _acquire_token_func, environment=self._azure_environment
        )
        # File downloads stream outside the SDK and carry the token themselves.
        self._acquire_token = _acquire_token_func

    @property
    def supports_sharepoint_rest(self) -> bool:
        return self._auth_method.supports_sharepoint_rest

    @property
    def graph_root(self) -> str:
        return f"{self.graph_api_host}/v1.0"

    def directory(self) -> UserDirectory:
        """The run's one user directory, also when workers ask for it at once. It
        lists nothing until a member without an email asks for a name."""
        with self._directory_lock:
            if self._user_directory is None:
                self._user_directory = UserDirectory(self.graph())
            return self._user_directory

    def graph(self) -> GraphClient:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams")
        return self.graph_client

    def access_token(self) -> str:
        if self._acquire_token is None:
            raise ConnectorMissingCredentialError("Teams")
        return self._acquire_token()["access_token"]

    def graph_api_client(self) -> GraphApiClient:
        if self._acquire_token is None:
            raise ConnectorMissingCredentialError("Teams")
        return GraphApiClient(self.access_token, self.graph_root)
