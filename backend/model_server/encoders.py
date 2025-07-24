import asyncio
import json
import time
from types import TracebackType
from typing import cast
from typing import Optional

import aioboto3  # type: ignore
import httpx
import openai
import vertexai  # type: ignore
import voyageai  # type: ignore
from cohere import AsyncClient as CohereAsyncClient
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from google.oauth2 import service_account  # type: ignore
from litellm import aembedding
from litellm.exceptions import RateLimitError
from retry import retry
from sentence_transformers import CrossEncoder  # type: ignore
from sentence_transformers import SentenceTransformer  # type: ignore
from vertexai.language_models import TextEmbeddingInput  # type: ignore
from vertexai.language_models import TextEmbeddingModel  # type: ignore

from model_server.constants import DEFAULT_COHERE_MODEL
from model_server.constants import DEFAULT_OPENAI_MODEL
from model_server.constants import DEFAULT_VERTEX_MODEL
from model_server.constants import DEFAULT_VOYAGE_MODEL
from model_server.constants import EmbeddingModelTextType
from model_server.constants import EmbeddingProvider
from model_server.utils import pass_aws_key
from model_server.utils import simple_log_function_time
from onyx.utils.logger import setup_logger
from shared_configs.configs import API_BASED_EMBEDDING_TIMEOUT
from shared_configs.configs import INDEXING_ONLY
from shared_configs.configs import OPENAI_EMBEDDING_TIMEOUT
from shared_configs.configs import VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE
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

# Authentication error string constants
_AUTH_ERROR_401 = "401"
_AUTH_ERROR_UNAUTHORIZED = "unauthorized"
_AUTH_ERROR_INVALID_API_KEY = "invalid api key"
_AUTH_ERROR_PERMISSION = "permission"


def is_authentication_error(error: Exception) -> bool:
    """Check if an exception is related to authentication issues.

    Args:
        error: The exception to check

    Returns:
        bool: True if the error appears to be authentication-related
    """
    error_str = str(error).lower()
    return (
        _AUTH_ERROR_401 in error_str
        or _AUTH_ERROR_UNAUTHORIZED in error_str
        or _AUTH_ERROR_INVALID_API_KEY in error_str
        or _AUTH_ERROR_PERMISSION in error_str
    )


def format_embedding_error(
    error: Exception,
    service_name: str,
    model: str | None,
    provider: EmbeddingProvider,
    sanitized_api_key: str | None = None,
    status_code: int | None = None,
) -> str:
    """
    Format a standardized error string for embedding errors.
    """
    detail = f"Status {status_code}" if status_code else f"{type(error)}"

    return (
        f"{'HTTP error' if status_code else 'Exception'} embedding text with {service_name} - {detail}: "
        f"Model: {model} "
        f"Provider: {provider} "
        f"API Key: {sanitized_api_key} "
        f"Exception: {error}"
    )


# Custom exception for authentication errors
class AuthenticationError(Exception):
    """Raised when authentication fails with a provider."""

    def __init__(self, provider: str, message: str = "API key is invalid or expired"):
        self.provider = provider
        self.message = message
        super().__init__(f"{provider} authentication failed: {message}")


class CloudEmbedding:
    def __init__(
        self,
        api_key: str,
        provider: EmbeddingProvider,
        api_url: str | None = None,
        api_version: str | None = None,
        timeout: int = API_BASED_EMBEDDING_TIMEOUT,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.api_url = api_url
        self.api_version = api_version
        self.timeout = timeout
        self.http_client = httpx.AsyncClient(timeout=timeout)
        self._closed = False
        self.sanitized_api_key = api_key[:4] + "********" + api_key[-4:]

    async def _embed_openai(
        self, texts: list[str], model: str | None, reduced_dimension: int | None
    ) -> list[Embedding]:
        if not model:
            model = DEFAULT_OPENAI_MODEL

        # Use the OpenAI specific timeout for this one
        client = openai.AsyncOpenAI(
            api_key=self.api_key, timeout=OPENAI_EMBEDDING_TIMEOUT
        )

        final_embeddings: list[Embedding] = []

        for text_batch in batch_list(texts, _OPENAI_MAX_INPUT_LEN):
            response = await client.embeddings.create(
                input=text_batch,
                model=model,
                dimensions=reduced_dimension or openai.NOT_GIVEN,
            )
            final_embeddings.extend(
                [embedding.embedding for embedding in response.data]
            )
        return final_embeddings

    async def _embed_cohere(
        self, texts: list[str], model: str | None, embedding_type: str
    ) -> list[Embedding]:
        if not model:
            model = DEFAULT_COHERE_MODEL

        client = CohereAsyncClient(api_key=self.api_key)

        final_embeddings: list[Embedding] = []
        for text_batch in batch_list(texts, _COHERE_MAX_INPUT_LEN):
            # Does not use the same tokenizer as the Onyx API server but it's approximately the same
            # empirically it's only off by a very few tokens so it's not a big deal
            response = await client.embed(
                texts=text_batch,
                model=model,
                input_type=embedding_type,
                truncate="END",
            )
            final_embeddings.extend(cast(list[Embedding], response.embeddings))
        return final_embeddings

    async def _embed_voyage(
        self, texts: list[str], model: str | None, embedding_type: str
    ) -> list[Embedding]:
        if not model:
            model = DEFAULT_VOYAGE_MODEL

        client = voyageai.AsyncClient(
            api_key=self.api_key, timeout=API_BASED_EMBEDDING_TIMEOUT
        )

        response = await client.embed(
            texts=texts,
            model=model,
            input_type=embedding_type,
            truncation=True,
        )
        return response.embeddings

    async def _embed_azure(
        self, texts: list[str], model: str | None
    ) -> list[Embedding]:
        response = await aembedding(
            model=model,
            input=texts,
            timeout=API_BASED_EMBEDDING_TIMEOUT,
            api_key=self.api_key,
            api_base=self.api_url,
            api_version=self.api_version,
        )
        embeddings = [embedding["embedding"] for embedding in response.data]
        return embeddings

    async def _embed_vertex(
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

        inputs = [TextEmbeddingInput(text, embedding_type) for text in texts]

        # Split into batches of 25 texts
        max_texts_per_batch = VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE
        batches = [
            inputs[i : i + max_texts_per_batch]
            for i in range(0, len(inputs), max_texts_per_batch)
        ]

        # Dispatch all embedding calls asynchronously at once
        tasks = [
            client.get_embeddings_async(batch, auto_truncate=True) for batch in batches
        ]

        # Wait for all tasks to complete in parallel
        results = await asyncio.gather(*tasks)

        return [embedding.values for batch in results for embedding in batch]

    async def _embed_litellm_proxy(
        self, texts: list[str], model_name: str | None
    ) -> list[Embedding]:
        if not model_name:
            raise ValueError("Model name is required for LiteLLM proxy embedding.")

        if not self.api_url:
            raise ValueError("API URL is required for LiteLLM proxy embedding.")

        headers = (
            {} if not self.api_key else {"Authorization": f"Bearer {self.api_key}"}
        )

        response = await self.http_client.post(
            self.api_url,
            json={
                "model": model_name,
                "input": texts,
            },
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()
        return [embedding["embedding"] for embedding in result["data"]]

    @retry(tries=_RETRY_TRIES, delay=_RETRY_DELAY)
    async def embed(
        self,
        *,
        texts: list[str],
        text_type: EmbedTextType,
        model_name: str | None = None,
        deployment_name: str | None = None,
        reduced_dimension: int | None = None,
    ) -> list[Embedding]:
        try:
            if self.provider == EmbeddingProvider.OPENAI:
                return await self._embed_openai(texts, model_name, reduced_dimension)
            elif self.provider == EmbeddingProvider.AZURE:
                return await self._embed_azure(texts, f"azure/{deployment_name}")
            elif self.provider == EmbeddingProvider.LITELLM:
                return await self._embed_litellm_proxy(texts, model_name)

            embedding_type = EmbeddingModelTextType.get_type(self.provider, text_type)
            if self.provider == EmbeddingProvider.COHERE:
                return await self._embed_cohere(texts, model_name, embedding_type)
            elif self.provider == EmbeddingProvider.VOYAGE:
                return await self._embed_voyage(texts, model_name, embedding_type)
            elif self.provider == EmbeddingProvider.GOOGLE:
                return await self._embed_vertex(texts, model_name, embedding_type)
            else:
                raise ValueError(f"Unsupported provider: {self.provider}")
        except openai.AuthenticationError:
            raise AuthenticationError(provider="OpenAI")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError(provider=str(self.provider))

            error_string = format_embedding_error(
                e,
                str(self.provider),
                model_name or deployment_name,
                self.provider,
                sanitized_api_key=self.sanitized_api_key,
                status_code=e.response.status_code,
            )
            logger.error(error_string)
            logger.debug(f"Exception texts: {texts}")

            raise RuntimeError(error_string)
        except Exception as e:
            if is_authentication_error(e):
                raise AuthenticationError(provider=str(self.provider))

            error_string = format_embedding_error(
                e,
                str(self.provider),
                model_name or deployment_name,
                self.provider,
                sanitized_api_key=self.sanitized_api_key,
            )
            logger.error(error_string)
            logger.debug(f"Exception texts: {texts}")

            raise RuntimeError(error_string)

    @staticmethod
    def create(
        api_key: str,
        provider: EmbeddingProvider,
        api_url: str | None = None,
        api_version: str | None = None,
    ) -> "CloudEmbedding":
        logger.debug(f"Creating Embedding instance for provider: {provider}")
        return CloudEmbedding(api_key, provider, api_url, api_version)

    async def aclose(self) -> None:
        """Explicitly close the client."""
        if not self._closed:
            await self.http_client.aclose()
            self._closed = True

    async def __aenter__(self) -> "CloudEmbedding":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __del__(self) -> None:
        """Finalizer to warn about unclosed clients."""
        if not self._closed:
            logger.warning(
                "CloudEmbedding was not properly closed. Use 'async with' or call aclose()"
            )


def get_embedding_model(
    model_name: str,
    max_context_length: int,
) -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer  # type: ignore

    global _GLOBAL_MODELS_DICT  # A dictionary to store models

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
async def embed_text(
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
    reduced_dimension: int | None,
    gpu_type: str = "UNKNOWN",
) -> list[Embedding]:
    if not all(texts):
        logger.error("Empty strings provided for embedding")
        raise ValueError("Empty strings are not allowed for embedding.")

    if not texts:
        logger.error("No texts provided for embedding")
        raise ValueError("No texts provided for embedding.")

    start = time.monotonic()

    total_chars = 0
    for text in texts:
        total_chars += len(text)

    if provider_type is not None:
        logger.info(
            f"Embedding {len(texts)} texts with {total_chars} total characters with provider: {provider_type}"
        )

        if api_key is None:
            logger.error("API key not provided for cloud model")
            raise RuntimeError("API key not provided for cloud model")

        if prefix:
            logger.warning("Prefix provided for cloud model, which is not supported")
            raise ValueError(
                "Prefix string is not valid for cloud models. "
                "Cloud models take an explicit text type instead."
            )

        async with CloudEmbedding(
            api_key=api_key,
            provider=provider_type,
            api_url=api_url,
            api_version=api_version,
        ) as cloud_model:
            embeddings = await cloud_model.embed(
                texts=texts,
                model_name=model_name,
                deployment_name=deployment_name,
                text_type=text_type,
                reduced_dimension=reduced_dimension,
            )

        if any(embedding is None for embedding in embeddings):
            error_message = "Embeddings contain None values\n"
            error_message += "Corresponding texts:\n"
            error_message += "\n".join(texts)
            logger.error(error_message)
            raise ValueError(error_message)

        elapsed = time.monotonic() - start
        logger.info(
            f"event=embedding_provider "
            f"texts={len(texts)} "
            f"chars={total_chars} "
            f"provider={provider_type} "
            f"elapsed={elapsed:.2f}"
        )
    elif model_name is not None:
        logger.info(
            f"Embedding {len(texts)} texts with {total_chars} total characters with local model: {model_name}"
        )

        prefixed_texts = [f"{prefix}{text}" for text in texts] if prefix else texts

        local_model = get_embedding_model(
            model_name=model_name, max_context_length=max_context_length
        )
        # Run CPU-bound embedding in a thread pool
        embeddings_vectors = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: local_model.encode(
                prefixed_texts, normalize_embeddings=normalize_embeddings
            ),
        )
        embeddings = [
            embedding if isinstance(embedding, list) else embedding.tolist()
            for embedding in embeddings_vectors
        ]

        elapsed = time.monotonic() - start
        logger.info(
            f"Successfully embedded {len(texts)} texts with {total_chars} total characters "
            f"with local model {model_name} in {elapsed:.2f}"
        )
        logger.info(
            f"event=embedding_model "
            f"texts={len(texts)} "
            f"chars={total_chars} "
            f"model={model_name} "
            f"gpu={gpu_type} "
            f"elapsed={elapsed:.2f}"
        )
    else:
        logger.error("Neither model name nor provider specified for embedding")
        raise ValueError(
            "Either model name or provider must be provided to run embeddings."
        )

    return embeddings


@simple_log_function_time()
async def local_rerank(query: str, docs: list[str], model_name: str) -> list[float]:
    cross_encoder = get_local_reranking_model(model_name)
    # Run CPU-bound reranking in a thread pool
    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: cross_encoder.predict([(query, doc) for doc in docs]).tolist(),  # type: ignore
    )


async def cohere_rerank_api(
    query: str, docs: list[str], model_name: str, api_key: str
) -> list[float]:
    cohere_client = CohereAsyncClient(api_key=api_key)
    response = await cohere_client.rerank(query=query, documents=docs, model=model_name)
    results = response.results
    sorted_results = sorted(results, key=lambda item: item.index)
    return [result.relevance_score for result in sorted_results]


async def cohere_rerank_aws(
    query: str,
    docs: list[str],
    model_name: str,
    region_name: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
) -> list[float]:
    session = aioboto3.Session(
        aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key
    )
    async with session.client(
        "bedrock-runtime", region_name=region_name
    ) as bedrock_client:
        body = json.dumps(
            {
                "query": query,
                "documents": docs,
                "api_version": 2,
            }
        )
        # Invoke the Bedrock model asynchronously
        response = await bedrock_client.invoke_model(
            modelId=model_name,
            accept="application/json",
            contentType="application/json",
            body=body,
        )

        # Read the response asynchronously
        response_body = json.loads(await response["body"].read())

        # Extract and sort the results
        results = response_body.get("results", [])
        sorted_results = sorted(results, key=lambda item: item["index"])

        return [result["relevance_score"] for result in sorted_results]


async def litellm_rerank(
    query: str, docs: list[str], api_url: str, model_name: str, api_key: str | None
) -> list[float]:
    headers = {} if not api_key else {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient() as client:
        response = await client.post(
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
async def route_bi_encoder_embed(
    request: Request,
    embed_request: EmbedRequest,
) -> EmbedResponse:
    return await process_embed_request(embed_request, request.app.state.gpu_type)


async def process_embed_request(
    embed_request: EmbedRequest, gpu_type: str = "UNKNOWN"
) -> EmbedResponse:
    if not embed_request.texts:
        raise HTTPException(status_code=400, detail="No texts to be embedded")

    if not all(embed_request.texts):
        raise ValueError("Empty strings are not allowed for embedding.")

    try:
        if embed_request.text_type == EmbedTextType.QUERY:
            prefix = embed_request.manual_query_prefix
        elif embed_request.text_type == EmbedTextType.PASSAGE:
            prefix = embed_request.manual_passage_prefix
        else:
            prefix = None

        embeddings = await embed_text(
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
            reduced_dimension=embed_request.reduced_dimension,
            prefix=prefix,
            gpu_type=gpu_type,
        )
        return EmbedResponse(embeddings=embeddings)
    except AuthenticationError as e:
        # Handle authentication errors consistently
        logger.error(f"Authentication error: {e.provider}")
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed: {e.message}",
        )
    except RateLimitError as e:
        raise HTTPException(
            status_code=429,
            detail=str(e),
        )
    except Exception as e:
        logger.exception(
            f"Error during embedding process: provider={embed_request.provider_type} model={embed_request.model_name}"
        )
        raise HTTPException(
            status_code=500, detail=f"Error during embedding process: {e}"
        )


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
            sim_scores = await local_rerank(
                query=rerank_request.query,
                docs=rerank_request.documents,
                model_name=rerank_request.model_name,
            )
            return RerankResponse(scores=sim_scores)
        elif rerank_request.provider_type == RerankerProvider.LITELLM:
            if rerank_request.api_url is None:
                raise ValueError("API URL is required for LiteLLM reranking.")

            sim_scores = await litellm_rerank(
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
            sim_scores = await cohere_rerank_api(
                query=rerank_request.query,
                docs=rerank_request.documents,
                model_name=rerank_request.model_name,
                api_key=rerank_request.api_key,
            )
            return RerankResponse(scores=sim_scores)

        elif rerank_request.provider_type == RerankerProvider.BEDROCK:
            if rerank_request.api_key is None:
                raise RuntimeError("Bedrock Rerank Requires an API Key")
            aws_access_key_id, aws_secret_access_key, aws_region = pass_aws_key(
                rerank_request.api_key
            )
            sim_scores = await cohere_rerank_aws(
                query=rerank_request.query,
                docs=rerank_request.documents,
                model_name=rerank_request.model_name,
                region_name=aws_region,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
            )
            return RerankResponse(scores=sim_scores)
        else:
            raise ValueError(f"Unsupported provider: {rerank_request.provider_type}")

    except Exception as e:
        logger.exception(f"Error during reranking process:\n{str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to run Cross-Encoder reranking"
        )
