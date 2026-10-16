"""Cloud embedding providers store their key as a shared API token."""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.api_token import get_api_token
from onyx.db.llm import (
    fetch_embedding_provider,
    remove_embedding_provider,
    upsert_cloud_embedding_provider,
)
from onyx.server.manage.api_token.models import ExistingApiToken, NewApiToken
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from shared_configs.enums import EmbeddingProvider

_PROVIDER = EmbeddingProvider.VOYAGE
_KEY = "pa-test-embedding-key-not-a-real-secret"


@pytest.fixture(autouse=True)
def _clear_provider(db_session: Session) -> Generator[None, None, None]:
    remove_embedding_provider(db_session, _PROVIDER)
    yield
    db_session.rollback()
    remove_embedding_provider(db_session, _PROVIDER)


def test_new_key_creates_a_token_for_the_provider_platform(
    db_session: Session,
) -> None:
    created = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=_PROVIDER,
            api_key=NewApiToken(value=_KEY),
            api_url="https://api.voyageai.example.com/v1",
        ),
    )

    assert created.api_token_id is not None
    assert created.api_key is not None and created.api_key != _KEY
    token = get_api_token(db_session, created.api_token_id)
    assert token is not None
    assert token.platform == _PROVIDER.value
    assert token.base_url == "https://api.voyageai.example.com/v1"
    assert token.value.get_value(apply_mask=False) == _KEY


def test_edit_with_the_existing_token_keeps_the_key(db_session: Session) -> None:
    created = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=_PROVIDER, api_key=NewApiToken(value=_KEY)
        ),
    )
    assert created.api_token_id is not None

    updated = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=_PROVIDER,
            api_key=ExistingApiToken(id=created.api_token_id),
            api_version="2",
        ),
    )

    assert updated.api_token_id == created.api_token_id
    stored = fetch_embedding_provider(db_session, _PROVIDER)
    assert stored is not None and stored.api_key is not None
    assert stored.api_key.get_value(apply_mask=False) == _KEY


def test_leaving_the_key_out_keeps_it_and_null_clears_it(
    db_session: Session,
) -> None:
    created = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=_PROVIDER, api_key=NewApiToken(value=_KEY)
        ),
    )
    assert created.api_token_id is not None

    kept = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(provider_type=_PROVIDER, api_version="2"),
    )
    assert kept.api_token_id == created.api_token_id

    cleared = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(provider_type=_PROVIDER, api_key=None),
    )
    assert cleared.api_token_id is None
    assert get_api_token(db_session, created.api_token_id) is None


def test_replacing_and_deleting_release_unused_tokens(db_session: Session) -> None:
    created = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=_PROVIDER, api_key=NewApiToken(value=_KEY)
        ),
    )
    first_token_id = created.api_token_id
    assert first_token_id is not None

    replaced = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=_PROVIDER, api_key=NewApiToken(value=f"{_KEY}-rotated")
        ),
    )
    assert replaced.api_token_id is not None
    assert replaced.api_token_id != first_token_id
    assert get_api_token(db_session, first_token_id) is None

    remove_embedding_provider(db_session, _PROVIDER)

    assert get_api_token(db_session, replaced.api_token_id) is None


def test_system_key_is_left_out_of_the_token_list(db_session: Session) -> None:
    created = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=_PROVIDER, api_key=NewApiToken(value=_KEY)
        ),
        system_key=True,
    )

    assert created.api_token_id is not None
    token = get_api_token(db_session, created.api_token_id)
    assert token is not None and token.is_system
