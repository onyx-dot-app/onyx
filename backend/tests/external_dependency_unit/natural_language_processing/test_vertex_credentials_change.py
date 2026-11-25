"""Tests that the Vertex credentials cache follows the key and the configuration
that the database holds for the Google embedding provider."""

import json
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.auth.credentials import Credentials
from sqlalchemy.orm import Session

from onyx.db.llm import (
    fetch_embedding_provider,
    remove_embedding_provider,
    upsert_cloud_embedding_provider,
)
from onyx.db.models import SearchSettings
from onyx.natural_language_processing.embedding_providers.vertex_credentials import (
    VERTEX_CREDENTIALS,
)
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from shared_configs.enums import EmbeddingProvider, EmbedTextType

_FROM_INFO = "google.oauth2.service_account.Credentials.from_service_account_info"


class _FakeVertex:
    """Records each credentials resolve and each client that a call makes."""

    def __init__(self) -> None:
        self.resolved_projects: list[str] = []
        self.client_credentials: list[Credentials] = []
        self.client_projects: list[str] = []
        self.client_locations: list[str] = []

    def resolve(self, info: dict[str, str], **_kwargs: object) -> MagicMock:
        self.resolved_projects.append(info["project_id"])
        return MagicMock(spec=Credentials)

    def client(
        self, *, credentials: Credentials, project: str, location: str, **_: object
    ) -> MagicMock:
        self.client_credentials.append(credentials)
        self.client_projects.append(project)
        self.client_locations.append(location)
        response = MagicMock()
        response.embeddings = [MagicMock(values=[0.1, 0.2])]
        client = MagicMock()
        client.aio.models.embed_content = AsyncMock(return_value=response)
        client.aio.aclose = AsyncMock()
        return client


@pytest.fixture
def vertex(db_session: Session) -> Generator[_FakeVertex, None, None]:
    remove_embedding_provider(db_session, EmbeddingProvider.GOOGLE)
    VERTEX_CREDENTIALS.clear()
    fake = _FakeVertex()
    try:
        with (
            patch(_FROM_INFO, side_effect=fake.resolve),
            patch("google.genai.Client", side_effect=fake.client),
            patch("onyx.natural_language_processing.search_nlp_models.get_tokenizer"),
        ):
            yield fake
    finally:
        VERTEX_CREDENTIALS.clear()
        db_session.rollback()
        remove_embedding_provider(db_session, EmbeddingProvider.GOOGLE)


def _store_provider(
    db_session: Session, project: str, location: str = "us-central1"
) -> None:
    upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.GOOGLE,
            api_key=json.dumps({"type": "service_account", "project_id": project}),
            api_key_changed=True,
            vertex_config=VertexEmbeddingConfig(location=location),
        ),
    )


def _embed_passage(db_session: Session) -> None:
    """Embeds one passage with a model that is built from the database, as
    each indexing task does."""
    db_session.expire_all()
    provider = fetch_embedding_provider(db_session, EmbeddingProvider.GOOGLE)
    assert provider is not None
    # Detached, so the SearchSettings below is not added to the session.
    db_session.expunge(provider)
    model = EmbeddingModel.from_db_model(
        SearchSettings(
            model_name="text-embedding-005",
            normalize=True,
            provider_type=EmbeddingProvider.GOOGLE,
            cloud_provider=provider,
        ),
        server_host="localhost",
        server_port=9000,
    )
    embeddings = model.encode(["some text"], text_type=EmbedTextType.PASSAGE)
    assert embeddings == [[0.1, 0.2]]


def test_changed_key_gets_new_credentials(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    vertex: _FakeVertex,
) -> None:
    # Key 1: the second call uses the cached credentials.
    _store_provider(db_session, "project-one")
    _embed_passage(db_session)
    _embed_passage(db_session)
    assert vertex.resolved_projects == ["project-one"]
    assert vertex.client_projects == ["project-one", "project-one"]
    key_one_credentials = vertex.client_credentials[0]
    assert vertex.client_credentials[1] is key_one_credentials

    # Key 2: the next call resolves the new key, and the cache holds it.
    _store_provider(db_session, "project-two")
    _embed_passage(db_session)
    _embed_passage(db_session)
    assert vertex.resolved_projects == ["project-one", "project-two"]
    assert vertex.client_projects[2:] == ["project-two", "project-two"]
    key_two_credentials = vertex.client_credentials[2]
    assert key_two_credentials is not key_one_credentials
    assert vertex.client_credentials[3] is key_two_credentials

    # Key 1 again: its entry is still in the cache.
    _store_provider(db_session, "project-one")
    _embed_passage(db_session)
    assert vertex.resolved_projects == ["project-one", "project-two"]
    assert vertex.client_projects[4] == "project-one"
    assert vertex.client_credentials[4] is key_one_credentials


def test_changed_configuration_gets_new_credentials(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    vertex: _FakeVertex,
) -> None:
    _store_provider(db_session, "project-one", location="us-central1")
    _embed_passage(db_session)

    # The same key with a different location.
    _store_provider(db_session, "project-one", location="europe-west4")
    _embed_passage(db_session)
    _embed_passage(db_session)

    assert vertex.resolved_projects == ["project-one", "project-one"]
    assert vertex.client_locations == ["us-central1", "europe-west4", "europe-west4"]
    assert vertex.client_credentials[1] is not vertex.client_credentials[0]
    assert vertex.client_credentials[2] is vertex.client_credentials[1]
