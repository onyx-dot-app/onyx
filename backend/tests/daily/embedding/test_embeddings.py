import os

import pytest

from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import EmbeddingProvider

VALID_SAMPLE = ["hi", "hello my name is bob", "woah there!!!. 😃"]
VALID_LONG_SAMPLE = ["hi " * 999]
# openai limit is 2048, cohere is supposed to be 96 but in practice that doesn't
# seem to be true
TOO_LONG_SAMPLE = ["a"] * 2500


def _run_embeddings(
    texts: list[str], embedding_model: EmbeddingModel, expected_dim: int
) -> None:
    for text_type in [EmbedTextType.QUERY, EmbedTextType.PASSAGE]:
        embeddings = embedding_model.encode(texts, text_type)
        assert len(embeddings) == len(texts)
        assert len(embeddings[0]) == expected_dim


@pytest.fixture
def openai_embedding_model() -> EmbeddingModel:
    return EmbeddingModel(
        server_host="localhost",
        server_port=9000,
        model_name="text-embedding-3-small",
        normalize=True,
        query_prefix=None,
        passage_prefix=None,
        api_key=os.getenv("OPENAI_API_KEY"),
        provider_type=EmbeddingProvider.OPENAI,
        api_url=None,
    )


def test_openai_embedding(openai_embedding_model: EmbeddingModel) -> None:
    _run_embeddings(VALID_SAMPLE, openai_embedding_model, 1536)
    _run_embeddings(TOO_LONG_SAMPLE, openai_embedding_model, 1536)


@pytest.fixture
def cohere_embedding_model() -> EmbeddingModel:
    return EmbeddingModel(
        server_host="localhost",
        server_port=9000,
        model_name="embed-english-light-v3.0",
        normalize=True,
        query_prefix=None,
        passage_prefix=None,
        api_key=os.getenv("COHERE_API_KEY"),
        provider_type=EmbeddingProvider.COHERE,
        api_url=None,
    )


def test_cohere_embedding(cohere_embedding_model: EmbeddingModel) -> None:
    _run_embeddings(VALID_SAMPLE, cohere_embedding_model, 384)
    _run_embeddings(TOO_LONG_SAMPLE, cohere_embedding_model, 384)


@pytest.fixture
def litellm_embedding_model() -> EmbeddingModel:
    return EmbeddingModel(
        server_host="localhost",
        server_port=9000,
        model_name="text-embedding-3-small",
        normalize=True,
        query_prefix=None,
        passage_prefix=None,
        api_key=os.getenv("LITELLM_API_KEY"),
        provider_type=EmbeddingProvider.LITELLM,
        api_url=os.getenv("LITELLM_API_URL"),
    )


@pytest.mark.skip(reason="re-enable when we can get the correct litellm key and url")
def test_litellm_embedding(litellm_embedding_model: EmbeddingModel) -> None:
    _run_embeddings(VALID_SAMPLE, litellm_embedding_model, 1536)
    _run_embeddings(TOO_LONG_SAMPLE, litellm_embedding_model, 1536)


@pytest.fixture
def local_nomic_embedding_model() -> EmbeddingModel:
    return EmbeddingModel(
        server_host="localhost",
        server_port=9000,
        model_name="nomic-ai/nomic-embed-text-v1",
        normalize=True,
        query_prefix="search_query: ",
        passage_prefix="search_document: ",
        api_key=None,
        provider_type=None,
        api_url=None,
    )


def test_local_nomic_embedding(local_nomic_embedding_model: EmbeddingModel) -> None:
    _run_embeddings(VALID_SAMPLE, local_nomic_embedding_model, 768)
    _run_embeddings(TOO_LONG_SAMPLE, local_nomic_embedding_model, 768)


@pytest.fixture
def azure_embedding_model() -> EmbeddingModel:
    return EmbeddingModel(
        server_host="localhost",
        server_port=9000,
        model_name="text-embedding-3-small",
        normalize=True,
        query_prefix=None,
        passage_prefix=None,
        api_key=os.getenv("AZURE_API_KEY"),
        provider_type=EmbeddingProvider.AZURE,
        api_url=os.getenv("AZURE_API_URL"),
    )


def test_azure_embedding(azure_embedding_model: EmbeddingModel) -> None:
    _run_embeddings(VALID_SAMPLE, azure_embedding_model, 1536)
    _run_embeddings(TOO_LONG_SAMPLE, azure_embedding_model, 1536)


# NOTE (chris): this test doesn't work, and I do not know why
# def test_azure_embedding_model_rate_limit(azure_embedding_model: EmbeddingModel):
#     """NOTE: this test relies on a very low rate limit for the Azure API +
#     this test only being run once in a 1 minute window"""
#     # VALID_LONG_SAMPLE is 999 tokens, so the second call should run into rate
#     # limits assuming the limit is 1000 tokens per minute
#     result = azure_embedding_model.encode(VALID_LONG_SAMPLE, EmbedTextType.QUERY)
#     assert len(result) == 1
#     assert len(result[0]) == 1536

#     # this should fail
#     with pytest.raises(ModelServerRateLimitError):
#         azure_embedding_model.encode(VALID_LONG_SAMPLE, EmbedTextType.QUERY)
#         azure_embedding_model.encode(VALID_LONG_SAMPLE, EmbedTextType.QUERY)
#         azure_embedding_model.encode(VALID_LONG_SAMPLE, EmbedTextType.QUERY)

#     # this should succeed, since passage requests retry up to 10 times
#     start = time.time()
#     result = azure_embedding_model.encode(VALID_LONG_SAMPLE, EmbedTextType.PASSAGE)
#     assert len(result) == 1
#     assert len(result[0]) == 1536
#     assert time.time() - start > 30  # make sure we waited, even though we hit rate limits
