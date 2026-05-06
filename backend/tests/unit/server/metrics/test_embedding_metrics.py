"""Tests for embedding Prometheus metrics."""

from unittest.mock import patch

from onyx.server.metrics.embedding import _client_duration
from onyx.server.metrics.embedding import _embedding_input_chars_total
from onyx.server.metrics.embedding import _embedding_requests_total
from onyx.server.metrics.embedding import _embedding_texts_total
from onyx.server.metrics.embedding import _embeddings_in_progress
from onyx.server.metrics.embedding import LOCAL_PROVIDER_LABEL
from onyx.server.metrics.embedding import observe_embedding_client
from onyx.server.metrics.embedding import provider_label
from onyx.server.metrics.embedding import PROVIDER_LABEL_NAME
from onyx.server.metrics.embedding import TEXT_TYPE_LABEL_NAME
from onyx.server.metrics.embedding import track_embedding_in_progress
from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType


class TestProviderLabel:
    def test_none_maps_to_local(self) -> None:
        assert provider_label(None) == LOCAL_PROVIDER_LABEL

    def test_enum_maps_to_value(self) -> None:
        assert provider_label(EmbeddingProvider.OPENAI) == "openai"
        assert provider_label(EmbeddingProvider.COHERE) == "cohere"


class TestObserveEmbeddingClient:
    def test_success_records_all_counters(self) -> None:
        # Precondition.
        provider = EmbeddingProvider.OPENAI
        text_type = EmbedTextType.QUERY
        labels = {
            PROVIDER_LABEL_NAME: provider.value,
            TEXT_TYPE_LABEL_NAME: text_type.value,
        }

        before_requests = _embedding_requests_total.labels(
            **labels, status="success"
        )._value.get()
        before_texts = _embedding_texts_total.labels(**labels)._value.get()
        before_chars = _embedding_input_chars_total.labels(**labels)._value.get()
        before_duration_sum = _client_duration.labels(**labels)._sum.get()

        test_duration_s = 0.123
        test_num_texts = 4
        test_num_chars = 200

        # Under test.
        observe_embedding_client(
            provider=provider,
            text_type=text_type,
            duration_s=test_duration_s,
            num_texts=test_num_texts,
            num_chars=test_num_chars,
            success=True,
        )

        # Postcondition.
        assert (
            _embedding_requests_total.labels(**labels, status="success")._value.get()
            == before_requests + 1
        )
        assert (
            _embedding_texts_total.labels(**labels)._value.get()
            == before_texts + test_num_texts
        )
        assert (
            _embedding_input_chars_total.labels(**labels)._value.get()
            == before_chars + test_num_chars
        )
        assert (
            _client_duration.labels(**labels)._sum.get()
            == before_duration_sum + test_duration_s
        )

    def test_failure_records_duration_and_failure_counter_only(self) -> None:
        # Precondition.
        provider = EmbeddingProvider.COHERE
        text_type = EmbedTextType.PASSAGE
        labels = {
            PROVIDER_LABEL_NAME: provider.value,
            TEXT_TYPE_LABEL_NAME: text_type.value,
        }

        before_failure = _embedding_requests_total.labels(
            **labels, status="failure"
        )._value.get()
        before_texts = _embedding_texts_total.labels(**labels)._value.get()
        before_chars = _embedding_input_chars_total.labels(**labels)._value.get()
        before_duration_sum = _client_duration.labels(**labels)._sum.get()

        test_duration_s = 0.5
        test_num_texts = 3
        test_num_chars = 150

        # Under test.
        observe_embedding_client(
            provider=provider,
            text_type=text_type,
            duration_s=test_duration_s,
            num_texts=test_num_texts,
            num_chars=test_num_chars,
            success=False,
        )

        # Postcondition.
        # Failure counter incremented.
        assert (
            _embedding_requests_total.labels(**labels, status="failure")._value.get()
            == before_failure + 1
        )
        # Duration still recorded.
        assert (
            _client_duration.labels(**labels)._sum.get()
            == before_duration_sum + test_duration_s
        )
        # Throughput counters NOT bumped on failure.
        assert _embedding_texts_total.labels(**labels)._value.get() == before_texts
        assert (
            _embedding_input_chars_total.labels(**labels)._value.get() == before_chars
        )

    def test_local_provider_uses_local_label(self) -> None:
        # Precondition.
        text_type = EmbedTextType.QUERY
        labels = {
            PROVIDER_LABEL_NAME: LOCAL_PROVIDER_LABEL,
            TEXT_TYPE_LABEL_NAME: text_type.value,
        }
        before = _embedding_requests_total.labels(
            **labels, status="success"
        )._value.get()

        test_duration_s = 0.05
        test_num_texts = 1
        test_num_chars = 10

        # Under test.
        observe_embedding_client(
            provider=None,
            text_type=text_type,
            duration_s=test_duration_s,
            num_texts=test_num_texts,
            num_chars=test_num_chars,
            success=True,
        )

        # Postcondition.
        assert (
            _embedding_requests_total.labels(**labels, status="success")._value.get()
            == before + 1
        )

    def test_exceptions_do_not_propagate(self) -> None:
        with patch.object(
            _embedding_requests_total,
            "labels",
            side_effect=RuntimeError("boom"),
        ):
            # Must not raise.
            observe_embedding_client(
                provider=EmbeddingProvider.OPENAI,
                text_type=EmbedTextType.QUERY,
                duration_s=0.1,
                num_texts=1,
                num_chars=10,
                success=True,
            )


class TestTrackEmbeddingInProgress:
    def test_gauge_increments_and_decrements(self) -> None:
        # Precondition.
        provider = EmbeddingProvider.OPENAI
        text_type = EmbedTextType.QUERY
        labels = {
            PROVIDER_LABEL_NAME: provider.value,
            TEXT_TYPE_LABEL_NAME: text_type.value,
        }
        before = _embeddings_in_progress.labels(**labels)._value.get()

        # Under test.
        with track_embedding_in_progress(provider, text_type):
            during = _embeddings_in_progress.labels(**labels)._value.get()
            assert during == before + 1

        # Postcondition.
        after = _embeddings_in_progress.labels(**labels)._value.get()
        assert after == before

    def test_gauge_decrements_on_exception(self) -> None:
        # Precondition.
        provider = EmbeddingProvider.COHERE
        text_type = EmbedTextType.PASSAGE
        labels = {
            PROVIDER_LABEL_NAME: provider.value,
            TEXT_TYPE_LABEL_NAME: text_type.value,
        }
        before = _embeddings_in_progress.labels(**labels)._value.get()

        # Under test.
        raised = False
        try:
            with track_embedding_in_progress(provider, text_type):
                raise ValueError("simulated embedding failure")
        except ValueError:
            raised = True
        assert raised

        # Postcondition.
        after = _embeddings_in_progress.labels(**labels)._value.get()
        assert after == before

    def test_local_provider_uses_local_label(self) -> None:
        # Precondition.
        text_type = EmbedTextType.QUERY
        labels = {
            PROVIDER_LABEL_NAME: LOCAL_PROVIDER_LABEL,
            TEXT_TYPE_LABEL_NAME: text_type.value,
        }
        before = _embeddings_in_progress.labels(**labels)._value.get()

        # Under test.
        with track_embedding_in_progress(None, text_type):
            during = _embeddings_in_progress.labels(**labels)._value.get()
            assert during == before + 1

        # Postcondition.
        after = _embeddings_in_progress.labels(**labels)._value.get()
        assert after == before

    def test_inc_exception_does_not_break_call(self) -> None:
        # Precondition.
        provider = EmbeddingProvider.VOYAGE
        text_type = EmbedTextType.QUERY
        labels = {
            PROVIDER_LABEL_NAME: provider.value,
            TEXT_TYPE_LABEL_NAME: text_type.value,
        }
        before = _embeddings_in_progress.labels(**labels)._value.get()

        # Under test.
        with patch.object(
            _embeddings_in_progress.labels(**labels),
            "inc",
            side_effect=RuntimeError("boom"),
        ):
            # Context manager should still yield without decrementing.
            with track_embedding_in_progress(provider, text_type):
                during = _embeddings_in_progress.labels(**labels)._value.get()
                assert during == before

        # Postcondition.
        after = _embeddings_in_progress.labels(**labels)._value.get()
        assert after == before
