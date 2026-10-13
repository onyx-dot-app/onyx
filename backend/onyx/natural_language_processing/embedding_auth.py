"""Provider authentication schemas and runtime credential resolution.

Secrets stay in encrypted API-key storage. Provider metadata contains no secrets.
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, SecretStr

from onyx.natural_language_processing.vertex_auth import (
    VertexEmbeddingConfig,
    VertexEmbeddingConfigDict,
    VertexEmbeddingCredentials,
    resolve_vertex_embedding_credentials,
    validate_vertex_embedding_config,
)
from shared_configs.enums import EmbeddingProvider

CredentialsT = TypeVar("CredentialsT", covariant=True)

# Gateways can front models without auth of their own.
_OPTIONAL_API_KEY_PROVIDERS: frozenset[EmbeddingProvider] = frozenset(
    {EmbeddingProvider.BIFROST, EmbeddingProvider.LITELLM}
)


class EmbeddingAuth(Protocol[CredentialsT]):
    @property
    def uses_api_key(self) -> bool:
        """Whether the stored API key column is meaningful for this auth."""
        ...

    @property
    def requires_api_key(self) -> bool:
        """Whether a key must be present before a request is made."""
        ...

    def validate_configuration(self) -> None: ...

    def validate_credentials(self) -> None: ...

    def resolve_credentials(self) -> CredentialsT: ...


class ApiKeyEmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: EmbeddingProvider
    api_key: SecretStr | None = None


class ApiKeyEmbeddingCredentials(BaseModel):
    # None only for providers in _OPTIONAL_API_KEY_PROVIDERS.
    api_key: SecretStr | None


class ApiKeyEmbeddingAuth(EmbeddingAuth[ApiKeyEmbeddingCredentials]):
    def __init__(self, config: ApiKeyEmbeddingConfig) -> None:
        self.config = config

    @property
    def uses_api_key(self) -> bool:
        return True

    @property
    def requires_api_key(self) -> bool:
        return self.config.provider not in _OPTIONAL_API_KEY_PROVIDERS

    def validate_configuration(self) -> None:
        pass

    def validate_credentials(self) -> None:
        if self.requires_api_key and self.config.api_key is None:
            raise ValueError("API key not provided for cloud model")

    def resolve_credentials(self) -> ApiKeyEmbeddingCredentials:
        self.validate_credentials()
        return ApiKeyEmbeddingCredentials(api_key=self.config.api_key)


class VertexEmbeddingAuth(EmbeddingAuth[VertexEmbeddingCredentials]):
    def __init__(
        self, config: VertexEmbeddingConfig, api_key: SecretStr | None
    ) -> None:
        self.config = config
        self._api_key = api_key

    @property
    def uses_api_key(self) -> bool:
        return self.config.auth_method == "service_account_json"

    @property
    def requires_api_key(self) -> bool:
        return self.uses_api_key

    def validate_configuration(self) -> None:
        validate_vertex_embedding_config(self.config)

    def validate_credentials(self) -> None:
        self.validate_configuration()
        if self.requires_api_key and (
            self._api_key is None or not self._api_key.get_secret_value()
        ):
            raise ValueError("Service account JSON is required for Google embeddings.")

    def resolve_credentials(self) -> VertexEmbeddingCredentials:
        self.validate_credentials()
        return resolve_vertex_embedding_credentials(
            self._api_key.get_secret_value() if self._api_key is not None else None,
            self.config,
        )


CloudEmbeddingAuth = ApiKeyEmbeddingAuth | VertexEmbeddingAuth


def build_embedding_auth(
    provider: EmbeddingProvider,
    api_key: str | None,
    vertex_config: VertexEmbeddingConfig | VertexEmbeddingConfigDict | None = None,
) -> CloudEmbeddingAuth:
    """Adapt the existing API/storage fields into the provider's auth schema."""
    auth: CloudEmbeddingAuth
    secret = SecretStr(api_key) if api_key is not None else None
    if provider == EmbeddingProvider.GOOGLE:
        config = (
            VertexEmbeddingConfig.model_validate(vertex_config)
            if vertex_config is not None
            else VertexEmbeddingConfig()
        )
        auth = VertexEmbeddingAuth(config, secret)
    else:
        if vertex_config is not None:
            raise ValueError(
                "Vertex configuration is only supported for Google embeddings."
            )
        auth = ApiKeyEmbeddingAuth(
            ApiKeyEmbeddingConfig(provider=provider, api_key=secret)
        )
    auth.validate_configuration()
    return auth
