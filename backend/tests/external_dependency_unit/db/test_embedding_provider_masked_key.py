"""Guards the cloud embedding provider's secret against a read-modify-write.

Reads mask `api_key`, so a client that reads a provider, edits an unrelated
field and writes the object back would otherwise persist the mask as the real
credential and lock itself out of the embedding service.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import (
    fetch_embedding_provider,
    remove_embedding_provider,
    upsert_cloud_embedding_provider,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from onyx.utils.encryption import mask_string
from shared_configs.enums import EmbeddingProvider

_REAL_KEY = "sk-test-embedding-key-not-a-real-secret"


@pytest.fixture(autouse=True)
def _clear_provider(db_session: Session) -> Generator[None, None, None]:
    # upsert commits, so a leftover row would give the "nothing to restore"
    # case something to restore.
    remove_embedding_provider(db_session, EmbeddingProvider.VOYAGE)
    db_session.commit()
    yield
    remove_embedding_provider(db_session, EmbeddingProvider.VOYAGE)
    db_session.commit()


def _stored_key(db_session: Session) -> str | None:
    stored = fetch_embedding_provider(db_session, EmbeddingProvider.VOYAGE)
    assert stored is not None
    return stored.api_key.get_value(apply_mask=False) if stored.api_key else None


def test_masked_key_write_back_keeps_the_stored_key(db_session: Session) -> None:
    created = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.VOYAGE, api_key=_REAL_KEY
        ),
    )
    # What any client sees on read.
    assert created.api_key is not None and created.api_key != _REAL_KEY

    # Write the masked value straight back, changing only an unrelated field.
    updated = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.VOYAGE,
            api_key=created.api_key,
            api_url="https://api.voyageai.example.com/v1",
        ),
    )

    assert _stored_key(db_session) == _REAL_KEY
    assert updated.api_url == "https://api.voyageai.example.com/v1"


def test_a_real_key_still_replaces_the_stored_one(db_session: Session) -> None:
    upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.VOYAGE, api_key=_REAL_KEY
        ),
    )
    upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.VOYAGE, api_key=_REAL_KEY + "-rotated"
        ),
    )

    assert _stored_key(db_session) == _REAL_KEY + "-rotated"


def test_a_masked_key_with_nothing_to_restore_is_rejected(db_session: Session) -> None:
    with pytest.raises(OnyxError):
        upsert_cloud_embedding_provider(
            db_session,
            CloudEmbeddingProviderCreationRequest(
                provider_type=EmbeddingProvider.VOYAGE, api_key="sk-t...cret"
            ),
        )


def test_a_real_key_shaped_like_a_placeholder_is_stored(db_session: Session) -> None:
    # "abcd...wxyz" matches the placeholder shape. Judging by shape alone would
    # swallow it and silently keep the old key, so the check compares against
    # this key's own mask instead.
    upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.VOYAGE, api_key=_REAL_KEY
        ),
    )
    lookalike = "abcd...wxyz"
    upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.VOYAGE, api_key=lookalike
        ),
    )

    assert _stored_key(db_session) == lookalike


def test_a_placeholder_shaped_stored_key_survives_a_write_back(
    db_session: Session,
) -> None:
    # Creation refuses a placeholder-shaped key, so a stored one can only come
    # from an older write. It cannot be told apart from a real key of the same
    # shape, so the write-back preserves it rather than failing the update.
    upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.VOYAGE, api_key=_REAL_KEY
        ),
    )
    lookalike = "abcd...wxyz"
    provider = fetch_embedding_provider(db_session, EmbeddingProvider.VOYAGE)
    assert provider is not None
    provider.api_key = lookalike  # ty: ignore[invalid-assignment]
    db_session.commit()

    updated = upsert_cloud_embedding_provider(
        db_session,
        CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.VOYAGE,
            api_key=mask_string(lookalike),
            api_url="https://api.voyageai.example.com/v1",
        ),
    )

    assert _stored_key(db_session) == lookalike
    assert updated.api_url == "https://api.voyageai.example.com/v1"
