import json
from typing import cast
from typing import Optional

import httpx
import openai
import vertexai  # type: ignore
import voyageai  # type: ignore
from cohere import Client as CohereClient
from fastapi import APIRouter
from fastapi import HTTPException
from google.oauth2 import service_account  # type: ignore
from litellm import embedding
from retry import retry
from sentence_transformers import CrossEncoder  # type: ignore
from sentence_transformers import SentenceTransformer  # type: ignore
from vertexai.language_models import TextEmbeddingInput  # type: ignore
from vertexai.language_models import TextEmbeddingModel  # type: ignore

from danswer.utils.logger import setup_logger
from model_server.constants import DEFAULT_COHERE_MODEL
from model_server.constants import DEFAULT_OPENAI_MODEL
from model_server.constants import DEFAULT_VERTEX_MODEL
from model_server.constants import DEFAULT_VOYAGE_MODEL
from model_server.constants import EmbeddingModelTextType
from model_server.constants import EmbeddingProvider
from model_server.utils import simple_log_function_time
from shared_configs.configs import API_BASED_EMBEDDING_TIMEOUT
from shared_configs.configs import INDEXING_ONLY
from shared_configs.configs import OPENAI_EMBEDDING_TIMEOUT
from shared_configs.enums import EmbedTextType
from shared_configs.enums import RerankerProvider
from shared_configs.model_server_models import Embedding
from shared_configs.model_server_models import EmbedRequest
from shared_configs.model_server_models import EmbedResponse
from shared_configs.model_server_models import RerankRequest
from shared_configs.model_server_models import RerankResponse
from shared_configs.utils import batch_list


logger = setup_logger()

router = APIRouter(prefix="/encoder")

_GLOBAL_MODELS_DICT: dict[str, "SentenceTransformer"] = {}
_RERANK_MODEL: Optional["CrossEncoder"] = None

# If we are not only indexing, dont want retry very long
_RETRY_DELAY = 10 if INDEXING_ONLY else 0.1
_RETRY_TRIES = 10 if INDEXING_ONLY else 2

# OpenAI only allows 2048 embeddings to be computed at once
_OPENAI_MAX_INPUT_LEN = 2048
# Cohere allows up to 96 embeddings in a single embedding calling
_COHERE_MAX_INPUT_LEN = 96


class CloudEmbedding:
    def __init__(
        self,
        api_key: str,
        provider: EmbeddingProvider,
        api_url: str | None = None,
        api_version: str | None = None,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.api_url = api_url
        self.api_version = api_version

    def _embed_openai(self, texts: list[str], model: str | None) -> list[Embedding]:
        if not model:
            model = DEFAULT_OPENAI_MODEL

        client = openai.OpenAI(api_key=self.api_key, timeout=OPENAI_EMBEDDING_TIMEOUT)

        final_embeddings: list[Embedding] = []
        try:
            for text_batch in batch_list(texts, _OPENAI_MAX_INPUT_LEN):
                response = client.embeddings.create(input=text_batch, model=model)
                final_embeddings.extend(
                    [embedding.embedding for embedding in response.data]
                )
            return final_embeddings
        except Exception as e:
            error_string = (
                f"Error embedding text with OpenAI: {str(e)} \n"
                f"Model: {model} \n"
                f"Provider: {self.provider} \n"
                f"Texts: {texts}"
            )
            logger.error(error_string)
            raise RuntimeError(error_string)

    def _embed_cohere(
        self, texts: list[str], model: str | None, embedding_type: str
    ) -> list[Embedding]:
        if not model:
            model = DEFAULT_COHERE_MODEL

        client = CohereClient(api_key=self.api_key, timeout=API_BASED_EMBEDDING_TIMEOUT)

        final_embeddings: list[Embedding] = []
        for text_batch in batch_list(texts, _COHERE_MAX_INPUT_LEN):
            # Does not use the same tokenizer as the Danswer API server but it's approximately the same
            # empirically it's only off by a very few tokens so it's not a big deal
            response = client.embed(
                texts=text_batch,
                model=model,
                input_type=embedding_type,
                truncate="END",
            )
            final_embeddings.extend(cast(list[Embedding], response.embeddings))
        return final_embeddings

    def _embed_voyage(
        self, texts: list[str], model: str | None, embedding_type: str
    ) -> list[Embedding]:
        if not model:
            model = DEFAULT_VOYAGE_MODEL

        client = voyageai.Client(
            api_key=self.api_key, timeout=API_BASED_EMBEDDING_TIMEOUT
        )

        response = client.embed(
            texts,
            model=model,
            input_type=embedding_type,
            truncation=True,
        )
        return response.embeddings

    def _embed_azure(self, texts: list[str], model: str | None) -> list[Embedding]:
        response = embedding(
            model=model,
            input=texts,
            timeout=API_BASED_EMBEDDING_TIMEOUT,
            api_key=self.api_key,
            api_base=self.api_url,
            api_version=self.api_version,
        )
        embeddings = [embedding["embedding"] for embedding in response.data]

        return embeddings

    def _embed_vertex(
        self, texts: list[str], model: str | None, embedding_type: str
    ) -> list[Embedding]:
        if not model:
            model = DEFAULT_VERTEX_MODEL

        credentials = service_account.Credentials.from_service_account_info(
            json.loads(self.api_key)
        )
        project_id = json.loads(self.api_key)["project_id"]
        vertexai.init(project=project_id, credentials=credentials)
        client = TextEmbeddingModel.from_pretrained(model)

        embeddings = client.get_embeddings(
            [
                TextEmbeddingInput(
                    text,
                    embedding_type,
                )
                for text in texts
            ],
            auto_truncate=True,  # Also this is default
        )
        return [embedding.values for embedding in embeddings]

    def _embed_litellm_proxy(
        self, texts: list[str], model_name: str | None
    ) -> list[Embedding]:
        if not model_name:
            raise ValueError("Model name is required for LiteLLM proxy embedding.")

        if not self.api_url:
            raise ValueError("API URL is required for LiteLLM proxy embedding.")

        headers = (
            {} if not self.api_key else {"Authorization": f"Bearer {self.api_key}"}
        )

        with httpx.Client() as client:
            response = client.post(
                self.api_url,
                json={
                    "model": model_name,
                    "input": texts,
                },
                headers=headers,
                timeout=API_BASED_EMBEDDING_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
            return [embedding["embedding"] for embedding in result["data"]]

    @retry(tries=_RETRY_TRIES, delay=_RETRY_DELAY)
    def embed(
        self,
        *,
        texts: list[str],
        text_type: EmbedTextType,
        model_name: str | None = None,
        deployment_name: str | None = None,
    ) -> list[Embedding]:
        try:
            if self.provider == EmbeddingProvider.OPENAI:
                return self._embed_openai(texts, model_name)
            elif self.provider == EmbeddingProvider.AZURE:
                return self._embed_azure(texts, f"azure/{deployment_name}")
            elif self.provider == EmbeddingProvider.LITELLM:
                return self._embed_litellm_proxy(texts, model_name)

            embedding_type = EmbeddingModelTextType.get_type(self.provider, text_type)
            if self.provider == EmbeddingProvider.COHERE:
                return self._embed_cohere(texts, model_name, embedding_type)
            elif self.provider == EmbeddingProvider.VOYAGE:
                return self._embed_voyage(texts, model_name, embedding_type)
            elif self.provider == EmbeddingProvider.GOOGLE:
                return self._embed_vertex(texts, model_name, embedding_type)
            else:
                raise ValueError(f"Unsupported provider: {self.provider}")
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error embedding text with {self.provider}: {str(e)}",
            )

    @staticmethod
    def create(
        api_key: str,
        provider: EmbeddingProvider,
        api_url: str | None = None,
        api_version: str | None = None,
    ) -> "CloudEmbedding":
        logger.debug(f"Creating Embedding instance for provider: {provider}")
        return CloudEmbedding(api_key, provider, api_url, api_version)


def get_embedding_model(
    model_name: str,
    max_context_length: int,
) -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer  # type: ignore

    global _GLOBAL_MODELS_DICT  # A dictionary to store models

    if _GLOBAL_MODELS_DICT is None:
        _GLOBAL_MODELS_DICT = {}

    if model_name not in _GLOBAL_MODELS_DICT:
        logger.notice(f"Loading {model_name}")
        # Some model architectures that aren't built into the Transformers or Sentence
        # Transformer need to be downloaded to be loaded locally. This does not mean
        # data is sent to remote servers for inference, however the remote code can
        # be fairly arbitrary so only use trusted models
        model = SentenceTransformer(
            model_name_or_path=model_name,
            trust_remote_code=True,
        )
        model.max_seq_length = max_context_length
        _GLOBAL_MODELS_DICT[model_name] = model
    elif max_context_length != _GLOBAL_MODELS_DICT[model_name].max_seq_length:
        _GLOBAL_MODELS_DICT[model_name].max_seq_length = max_context_length

    return _GLOBAL_MODELS_DICT[model_name]


def get_local_reranking_model(
    model_name: str,
) -> CrossEncoder:
    global _RERANK_MODEL
    if _RERANK_MODEL is None:
        logger.notice(f"Loading {model_name}")
        model = CrossEncoder(model_name)
        _RERANK_MODEL = model
    return _RERANK_MODEL


@simple_log_function_time()
def embed_text(
    texts: list[str],
    text_type: EmbedTextType,
    model_name: str | None,
    deployment_name: str | None,
    max_context_length: int,
    normalize_embeddings: bool,
    api_key: str | None,
    provider_type: EmbeddingProvider | None,
    prefix: str | None,
    api_url: str | None,
    api_version: str | None,
) -> list[Embedding]:
    logger.info(f"Embedding {len(texts)} texts with provider: {provider_type}")

    if not all(texts):
        logger.error("Empty strings provided for embedding")
        raise ValueError("Empty strings are not allowed for embedding.")

    if not texts:
        logger.error("No texts provided for embedding")
        raise ValueError("No texts provided for embedding.")

    if provider_type is not None:
        logger.debug(f"Using cloud provider {provider_type} for embedding")
        if api_key is None:
            logger.error("API key not provided for cloud model")
            raise RuntimeError("API key not provided for cloud model")

        if prefix:
            logger.warning("Prefix provided for cloud model, which is not supported")
            raise ValueError(
                "Prefix string is not valid for cloud models. "
                "Cloud models take an explicit text type instead."
            )

        cloud_model = CloudEmbedding(
            api_key=api_key,
            provider=provider_type,
            api_url=api_url,
            api_version=api_version,
        )
        embeddings = cloud_model.embed(
            texts=texts,
            model_name=model_name,
            deployment_name=deployment_name,
            text_type=text_type,
        )

        if any(embedding is None for embedding in embeddings):
            error_message = "Embeddings contain None values\n"
            error_message += "Corresponding texts:\n"
            error_message += "\n".join(texts)
            logger.error(error_message)
            raise ValueError(error_message)

    elif model_name is not None:
        logger.debug(f"Using local model {model_name} for embedding")
        prefixed_texts = [f"{prefix}{text}" for text in texts] if prefix else texts

        local_model = get_embedding_model(
            model_name=model_name, max_context_length=max_context_length
        )
        embeddings_vectors = local_model.encode(
            prefixed_texts, normalize_embeddings=normalize_embeddings
        )
        embeddings = [
            embedding if isinstance(embedding, list) else embedding.tolist()
            for embedding in embeddings_vectors
        ]

    else:
        logger.error("Neither model name nor provider specified for embedding")
        raise ValueError(
            "Either model name or provider must be provided to run embeddings."
        )

    logger.info(f"Successfully embedded {len(texts)} texts")
    return embeddings


@simple_log_function_time()
def local_rerank(query: str, docs: list[str], model_name: str) -> list[float]:
    cross_encoder = get_local_reranking_model(model_name)
    return cross_encoder.predict([(query, doc) for doc in docs]).tolist()  # type: ignore


def cohere_rerank(
    query: str, docs: list[str], model_name: str, api_key: str
) -> list[float]:
    cohere_client = CohereClient(api_key=api_key)
    response = cohere_client.rerank(query=query, documents=docs, model=model_name)
    results = response.results
    sorted_results = sorted(results, key=lambda item: item.index)
    return [result.relevance_score for result in sorted_results]


def litellm_rerank(
    query: str, docs: list[str], api_url: str, model_name: str, api_key: str | None
) -> list[float]:
    headers = {} if not api_key else {"Authorization": f"Bearer {api_key}"}
    with httpx.Client() as client:
        response = client.post(
            api_url,
            json={
                "model": model_name,
                "query": query,
                "documents": docs,
            },
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()
        return [
            item["relevance_score"]
            for item in sorted(result["results"], key=lambda x: x["index"])
        ]


@router.post("/bi-encoder-embed")
async def process_embed_request(
    embed_request: EmbedRequest,
) -> EmbedResponse:
    if not embed_request.texts:
        raise HTTPException(status_code=400, detail="No texts to be embedded")
    elif not all(embed_request.texts):
        raise ValueError("Empty strings are not allowed for embedding.")

    try:
        if embed_request.text_type == EmbedTextType.QUERY:
            prefix = embed_request.manual_query_prefix
        elif embed_request.text_type == EmbedTextType.PASSAGE:
            prefix = embed_request.manual_passage_prefix
        else:
            prefix = None

        embeddings = embed_text(
            texts=embed_request.texts,
            model_name=embed_request.model_name,
            deployment_name=embed_request.deployment_name,
            max_context_length=embed_request.max_context_length,
            normalize_embeddings=embed_request.normalize_embeddings,
            api_key=embed_request.api_key,
            provider_type=embed_request.provider_type,
            text_type=embed_request.text_type,
            api_url=embed_request.api_url,
            api_version=embed_request.api_version,
            prefix=prefix,
        )
        return EmbedResponse(embeddings=embeddings)
    except Exception as e:
        exception_detail = f"Error during embedding process:\n{str(e)}"
        logger.exception(exception_detail)
        raise HTTPException(status_code=500, detail=exception_detail)


@router.post("/cross-encoder-scores")
async def process_rerank_request(rerank_request: RerankRequest) -> RerankResponse:
    """Cross encoders can be purely black box from the app perspective"""
    if INDEXING_ONLY:
        raise RuntimeError("Indexing model server should not call intent endpoint")

    if not rerank_request.documents or not rerank_request.query:
        raise HTTPException(
            status_code=400, detail="Missing documents or query for reranking"
        )
    if not all(rerank_request.documents):
        raise ValueError("Empty documents cannot be reranked.")

    try:
        if rerank_request.provider_type is None:
            sim_scores = local_rerank(
                query=rerank_request.query,
                docs=rerank_request.documents,
                model_name=rerank_request.model_name,
            )
            return RerankResponse(scores=sim_scores)
        elif rerank_request.provider_type == RerankerProvider.LITELLM:
            if rerank_request.api_url is None:
                raise ValueError("API URL is required for LiteLLM reranking.")

            sim_scores = litellm_rerank(
                query=rerank_request.query,
                docs=rerank_request.documents,
                api_url=rerank_request.api_url,
                model_name=rerank_request.model_name,
                api_key=rerank_request.api_key,
            )

            return RerankResponse(scores=sim_scores)

        elif rerank_request.provider_type == RerankerProvider.COHERE:
            if rerank_request.api_key is None:
                raise RuntimeError("Cohere Rerank Requires an API Key")
            sim_scores = cohere_rerank(
                query=rerank_request.query,
                docs=rerank_request.documents,
                model_name=rerank_request.model_name,
                api_key=rerank_request.api_key,
            )
            return RerankResponse(scores=sim_scores)
        else:
            raise ValueError(f"Unsupported provider: {rerank_request.provider_type}")
    except Exception as e:
        logger.exception(f"Error during reranking process:\n{str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to run Cross-Encoder reranking"
        )
