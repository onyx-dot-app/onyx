"""Tests that the cache is wired correctly into ``get_query_embeddings``."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.context.search.models import ChunkIndexRequest, IndexFilters
from onyx.context.search.retrieval.search_runner import search_chunks
from onyx.context.search.utils import get_query_embeddings
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import CloudEmbeddingProvider, SearchSettings
from onyx.document_index.interfaces import DocumentIndex
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from shared_configs.contextvars import CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR
from shared_configs.enums import EmbeddingProvider, EmbedTextType


def _make_fake_embedding_model(
    encode_return: list[list[float]],
    settings_id: int | None = 1,
) -> tuple[MagicMock, MagicMock]:
    """Returns ``(model_mock, encode_mock)`` so callers can inspect calls."""
    model = MagicMock(spec=EmbeddingModel)
    model.query_embedding_cache_key = (
        str(settings_id) if settings_id is not None else None
    )
    model.retrim_content = False
    model.provider_type = None
    encode = MagicMock(return_value=encode_return)
    model.encode = encode
    return model, encode


class TestWiring:
    def test_second_call_skips_encode_after_cache_warm(
        self,
        full_deployment_setup: None,  # noqa: ARG002
        db_session: Session,
        test_embedding: list[float],
    ) -> None:
        """
        Tests that the second call to get_query_embeddings skips the encode call
        after the cache is warmed.
        """
        # Precondition.
        # Make a unique query so prior test runs don't pollute the assertion.
        query = f"testing wiring {uuid4().hex[:8]}"
        emb = [test_embedding]

        model, encode = _make_fake_embedding_model(emb)
        first = get_query_embeddings(
            queries=[query], db_session=db_session, embedding_model=model
        )
        assert first == emb
        assert encode.call_count == 1

        # Same query, fresh model -> cache hit, encode must NOT be invoked. This
        # is because SearchSettings ID is used for the cache key, not the model.
        model2, encode2 = _make_fake_embedding_model([[0.0, 0.0, 0.0]])

        # Under test.
        second = get_query_embeddings(
            queries=[query], db_session=db_session, embedding_model=model2
        )

        # Postcondition.
        assert encode2.call_count == 0
        assert second == first

    def test_partial_fill_only_encodes_misses(
        self,
        full_deployment_setup: None,  # noqa: ARG002
        db_session: Session,
    ) -> None:
        """
        Tests that the encode call is only called for the queries that are not
        in the cache.
        """
        # Precondition.
        q_hit = f"testing partial hit {uuid4().hex[:8]}"
        q_miss = f"testing partial miss {uuid4().hex[:8]}"

        model, encode = _make_fake_embedding_model([[1.0, 1.0]])
        get_query_embeddings(
            queries=[q_hit], db_session=db_session, embedding_model=model
        )
        assert encode.call_count == 1

        # Now ask for [hit, miss, hit]; encode must be called only once,
        # with exactly the missing query.
        model2, encode2 = _make_fake_embedding_model([[2.0, 2.0]])

        # Under test.
        results = get_query_embeddings(
            queries=[q_hit, q_miss, q_hit],
            db_session=db_session,
            embedding_model=model2,
        )

        # Postcondition.
        assert encode2.call_count == 1
        miss_call = encode2.call_args_list[0]
        assert miss_call.args[0] == [q_miss]
        assert miss_call.kwargs.get("text_type") == EmbedTextType.QUERY

        assert results[0] == [1.0, 1.0]
        assert results[1] == [2.0, 2.0]
        assert results[2] == [1.0, 1.0]

    def test_disabled_flag_skips_cache(
        self,
        full_deployment_setup: None,  # noqa: ARG002
        db_session: Session,
    ) -> None:
        """
        Tests that the cache is skipped when the cache is disabled.
        """
        # Precondition.
        query = "testing disabled cache"

        model, encode = _make_fake_embedding_model([[7.0]])
        with patch("onyx.context.search.utils.QUERY_EMBEDDING_CACHE_ENABLED", False):
            # Under test.
            get_query_embeddings(
                queries=[query], db_session=db_session, embedding_model=model
            )
            # Second call should also encode, since cache is off.
            get_query_embeddings(
                queries=[query], db_session=db_session, embedding_model=model
            )

        # Postcondition.
        assert encode.call_count == 2

    def test_search_settings_id_drives_isolation(
        self,
        full_deployment_setup: None,  # noqa: ARG002
        db_session: Session,
    ) -> None:
        """
        Tests that different search settings IDs are isolated from each other
        even for the same query.
        """
        # Precondition.
        query = f"testing search settings isolation {uuid4().hex[:8]}"
        emb = [[9.0, 9.0]]

        model, _ = _make_fake_embedding_model(emb)
        get_query_embeddings(
            queries=[query], db_session=db_session, embedding_model=model
        )

        # A prefetched model can differ from the current database settings.
        model2, encode2 = _make_fake_embedding_model([[8.0, 8.0]], settings_id=2)
        get_query_embeddings(
            queries=[query], db_session=db_session, embedding_model=model2
        )
        assert encode2.call_count == 1


def test_prefetched_model_reuses_embedding_across_searches() -> None:
    query = f"prefetched query {uuid4().hex}\ud800"
    index = MagicMock(spec=DocumentIndex)
    index.hybrid_retrieval.return_value = []
    request = ChunkIndexRequest(
        query=query, filters=IndexFilters(access_control_list=[])
    )

    with (
        patch("onyx.natural_language_processing.search_nlp_models.get_tokenizer"),
        patch.object(
            EmbeddingModel, "encode", side_effect=[[[0.5]], [[0.25]], [[0.125]]]
        ) as encode,
    ):
        for settings_id, deployment in (
            (1, "first"),
            (1, "first"),
            (2, "first"),
            (2, "second"),
        ):
            model = EmbeddingModel.from_db_model(
                SearchSettings(
                    id=settings_id,
                    model_name="test",
                    normalize=True,
                    provider_type=EmbeddingProvider.AZURE,
                    cloud_provider=CloudEmbeddingProvider(
                        provider_type=EmbeddingProvider.AZURE,
                        deployment_name=deployment,
                    ),
                ),
                server_host="localhost",
                server_port=9000,
            )
            search_chunks(
                query_request=request,
                user_id=None,
                document_index=index,
                embedding_model=model,
                prefetched_federated_retrieval_infos=[],
            )

    assert encode.call_count == 3
    vectors = [
        call.kwargs["query_embedding"] for call in index.hybrid_retrieval.call_args_list
    ]
    assert vectors == [[0.5], [0.5], [0.25], [0.125]]


@pytest.mark.parametrize(
    ("settings_id", "retrim", "mode"),
    [
        (None, False, None),
        (1, True, None),
        (1, False, IncognitoRecordMode.USAGE_ONLY),
    ],
)
def test_uncacheable_queries_encode_each_time(
    settings_id: int | None, retrim: bool, mode: IncognitoRecordMode | None
) -> None:
    query = f"uncacheable query {uuid4().hex}"
    model, encode = _make_fake_embedding_model([[0.5]], settings_id=settings_id)
    model.retrim_content = retrim
    token = CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.set(mode)
    try:
        with (
            patch("onyx.context.search.utils.get_cached_query_embeddings") as read,
            patch("onyx.context.search.utils.cache_query_embeddings") as write,
        ):
            for _ in range(2):
                get_query_embeddings([query], embedding_model=model)
            read.assert_not_called()
            write.assert_not_called()
    finally:
        CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.reset(token)
    assert encode.call_count == 2
