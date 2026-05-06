"""Tests that the cache is wired correctly into ``get_query_embeddings``."""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.context.search.utils import get_query_embeddings
from onyx.db.search_settings import get_current_search_settings
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from shared_configs.enums import EmbedTextType


def _make_fake_embedding_model(
    encode_return: list[list[float]],
) -> tuple[MagicMock, MagicMock]:
    """Returns ``(model_mock, encode_mock)`` so callers can inspect calls."""
    model = MagicMock(spec=EmbeddingModel)
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

        # Pretend a different active model is in use; the cache key is
        # built from search_settings.id, so a different id means a miss.
        real_settings = get_current_search_settings(db_session)
        fake = MagicMock()
        fake.id = real_settings.id + 999_999
        with patch(
            "onyx.context.search.utils.get_current_search_settings",
            return_value=fake,
        ):
            # Under test.
            model2, encode2 = _make_fake_embedding_model([[8.0, 8.0]])
            get_query_embeddings(
                queries=[query],
                db_session=db_session,
                embedding_model=model2,
            )

            # Postcondition.
            assert encode2.call_count == 1
