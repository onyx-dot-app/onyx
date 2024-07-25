from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from danswer.db.models import CloudEmbeddingProvider as CloudEmbeddingProviderModel


class TestEmbeddingRequest(BaseModel):
    provider: str
    api_key: str | None = None


class CloudEmbeddingProvider(BaseModel):
    name: str
    api_key: str | None = None
    default_model_id: int | None = None
    id: int

    @classmethod
    def from_request(
        cls, cloud_provider_model: "CloudEmbeddingProviderModel"
    ) -> "CloudEmbeddingProvider":
        return cls(
            id=cloud_provider_model.id,
            name=cloud_provider_model.name,
            api_key=cloud_provider_model.api_key,
            default_model_id=cloud_provider_model.default_model_id,
        )


class CloudEmbeddingProviderCreationRequest(BaseModel):
    name: str
    api_key: str | None = None
    default_model_id: int | None = None
