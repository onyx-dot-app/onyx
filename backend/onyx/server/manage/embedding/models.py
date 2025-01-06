from typing import TYPE_CHECKING

from pydantic import BaseModel

from shared_configs.enums import EmbeddingProvider

if TYPE_CHECKING:
    from onyx.db.models import CloudEmbeddingProvider as CloudEmbeddingProviderModel


class SearchSettingsDeleteRequest(BaseModel):
    search_settings_id: int


class TestEmbeddingRequest(BaseModel):
    provider_type: EmbeddingProvider
    api_key: str | None = None
    api_url: str | None = None
    model_name: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None

    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}


class CloudEmbeddingProvider(BaseModel):
    provider_type: EmbeddingProvider
    api_key: str | None = None
    api_url: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None

    @classmethod
    def from_request(
        cls, cloud_provider_model: "CloudEmbeddingProviderModel"
    ) -> "CloudEmbeddingProvider":
        return cls(
            provider_type=cloud_provider_model.provider_type,
            api_key=cloud_provider_model.api_key,
            api_url=cloud_provider_model.api_url,
            api_version=cloud_provider_model.api_version,
            deployment_name=cloud_provider_model.deployment_name,
        )


class CloudEmbeddingProviderCreationRequest(BaseModel):
    provider_type: EmbeddingProvider
    api_key: str | None = None
    api_url: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None
