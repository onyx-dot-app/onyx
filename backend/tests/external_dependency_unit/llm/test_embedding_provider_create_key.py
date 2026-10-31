"""api_key_changed=False says "keep the stored key". On create there is no
stored key, so that branch must not resolve to nothing and drop a real one.

Lives beside the other onyx/db/llm.py cases rather than with the masked-key
suite, which sits in a directory this environment cannot write.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.llm import remove_embedding_provider, upsert_cloud_embedding_provider
from onyx.db.models import CloudEmbeddingProvider as CloudEmbeddingProviderModel
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from shared_configs.enums import EmbeddingProvider

_PROVIDER = EmbeddingProvider.VOYAGE
_REAL_KEY = "pa-not-a-mask-0000000000000000000000000"


def _stored_key(db_session: Session) -> str | None:
    provider = db_session.scalar(
        select(CloudEmbeddingProviderModel).where(
            CloudEmbeddingProviderModel.provider_type == _PROVIDER
        )
    )
    if provider is None or provider.api_key is None:
        return None
    return provider.api_key.get_value(apply_mask=False)


def test_creating_a_provider_keeps_a_real_key_sent_with_changed_false(
    db_session: Session,
) -> None:
    try:
        upsert_cloud_embedding_provider(
            db_session,
            CloudEmbeddingProviderCreationRequest(
                provider_type=_PROVIDER,
                api_key=_REAL_KEY,
                api_key_changed=False,
            ),
        )

        assert _stored_key(db_session) == _REAL_KEY, (
            "There is nothing stored to keep, so the sent key is the only one"
        )
    finally:
        db_session.rollback()
        remove_embedding_provider(db_session, _PROVIDER)


def test_creating_a_provider_still_refuses_a_bare_mask(
    db_session: Session,
) -> None:
    try:
        with pytest.raises(OnyxError):
            upsert_cloud_embedding_provider(
                db_session,
                CloudEmbeddingProviderCreationRequest(
                    provider_type=_PROVIDER,
                    api_key="pa-n...0000",
                    api_key_changed=False,
                ),
            )
    finally:
        db_session.rollback()
        remove_embedding_provider(db_session, _PROVIDER)
