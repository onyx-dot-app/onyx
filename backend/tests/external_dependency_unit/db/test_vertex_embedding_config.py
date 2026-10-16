from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import (
    fetch_embedding_provider,
    remove_embedding_provider,
    upsert_cloud_embedding_provider,
)
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
from onyx.server.manage.api_token.models import ExistingApiToken, NewApiToken
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from shared_configs.enums import EmbeddingProvider


@pytest.fixture(autouse=True)
def _clear_google_provider(db_session: Session) -> Generator[None, None, None]:
    remove_embedding_provider(db_session, EmbeddingProvider.GOOGLE)
    yield
    db_session.rollback()
    remove_embedding_provider(db_session, EmbeddingProvider.GOOGLE)


def test_legacy_edit_preserves_keyless_workload_identity(db_session: Session) -> None:
    config = VertexEmbeddingConfig(
        auth_method="workload_identity", project_id="vertex-project", location="global"
    )
    upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.GOOGLE, vertex_config=config
        ),
    )

    updated = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(provider_type=EmbeddingProvider.GOOGLE),
    )

    assert updated.vertex_config == config
    assert updated.api_key is None


def test_legacy_credential_replaces_workload_identity(db_session: Session) -> None:
    upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.GOOGLE,
            vertex_config=VertexEmbeddingConfig(
                auth_method="workload_identity", project_id="vertex-project"
            ),
        ),
    )
    updated = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.GOOGLE,
            api_key=NewApiToken(value="test-service-account-json"),
        ),
    )

    assert updated.vertex_config is None
    stored = fetch_embedding_provider(db_session, EmbeddingProvider.GOOGLE)
    assert stored is not None and stored.api_key is not None
    assert stored.api_key.get_value(apply_mask=False) == "test-service-account-json"


def test_legacy_edit_preserves_service_account_location(db_session: Session) -> None:
    config = VertexEmbeddingConfig(location="us-central1")
    created = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.GOOGLE,
            api_key=NewApiToken(value="test-service-account-json"),
            vertex_config=config,
        ),
    )
    assert created.api_token_id is not None
    updated = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.GOOGLE,
            api_key=ExistingApiToken(id=created.api_token_id),
        ),
    )

    assert updated.vertex_config == config
    assert updated.api_key is not None
