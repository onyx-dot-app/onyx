import asyncio
import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from functools import wraps
from types import TracebackType
from typing import Any
from typing import cast

import aioboto3  # type: ignore
import httpx
import requests
import voyageai  # type: ignore
from cohere import AsyncClient as CohereAsyncClient
from google.oauth2 import service_account  # type: ignore
from httpx import HTTPError
from requests import JSONDecodeError
from requests import RequestException
from requests import Response
from retry import retry

from onyx.configs.app_configs import INDEXING_EMBEDDING_MODEL_NUM_THREADS
from onyx.configs.app_configs import LARGE_CHUNK_RATIO
from onyx.configs.model_configs import BATCH_SIZE_ENCODE_CHUNKS
from onyx.configs.model_configs import (
    BATCH_SIZE_ENCODE_CHUNKS_FOR_API_EMBEDDING_SERVICES,
)
from onyx.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from onyx.connectors.models import ConnectorStopSignal
from onyx.db.models import SearchSettings
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.natural_language_processing.constants import DEFAULT_COHERE_MODEL
from onyx.natural_language_processing.constants import DEFAULT_OPENAI_MODEL
from onyx.natural_language_processing.constants import DEFAULT_VERTEX_MODEL
from onyx.natural_language_processing.constants import DEFAULT_VOYAGE_MODEL
from onyx.natural_language_processing.constants import EmbeddingModelTextType
from onyx.natural_language_processing.exceptions import (
    ModelServerRateLimitError,
)
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.natural_language_processing.utils import tokenizer_trim_content
from onyx.utils.logger import setup_logger
from onyx.utils.search_nlp_models_utils import pass_aws_key
from shared_configs.configs import API_BASED_EMBEDDING_TIMEOUT
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import INDEXING_MODEL_SERVER_PORT
from shared_configs.configs import INDEXING_ONLY
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.configs import OPENAI_EMBEDDING_TIMEOUT
from shared_configs.configs import SKIP_WARM_UP
from shared_configs.configs import VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE
from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType
from shared_configs.enums import RerankerProvider
from shared_configs.model_server_models import ConnectorClassificationRequest
from shared_configs.model_server_models import ConnectorClassificationResponse
from shared_configs.model_server_models import ContentClassificationPrediction
from shared_configs.model_server_models import Embedding
from shared_configs.model_server_models import EmbedRequest
from shared_configs.model_server_models import EmbedResponse
from shared_configs.model_server_models import InformationContentClassificationResponses
from shared_configs.model_server_models import IntentRequest
from shared_configs.model_server_models import IntentResponse
from shared_configs.model_server_models import RerankRequest
from shared_configs.model_server_models import RerankResponse
from shared_configs.utils import batch_list

logger = setup_logger()

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


WARM_UP_STRINGS = [
    "Onyx is amazing!",
    "Check out our easy deployment guide at",
    "https://docs.onyx.app/deployment/getting_started/quickstart",
]


def clean_model_name(model_str: str) -> str:
    return model_str.replace("/", "_").replace("-", "_").replace(".", "_")


def build_model_server_url(
    model_server_host: str,
    model_server_port: int,
) -> str:
    model_server_url = f"{model_server_host}:{model_server_port}"

    # use protocol if provided
    if "http" in model_server_url:
        return model_server_url

    # otherwise default to http
    return f"http://{model_server_url}"


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

        import openai

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
        from litellm import aembedding

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
        import vertexai  # type: ignore[import-untyped]
        from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput  # type: ignore[import-untyped]

        if not model:
            model = DEFAULT_VERTEX_MODEL

        service_account_info = json.loads(self.api_key)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info
        )
        project_id = service_account_info["project_id"]
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
            client.get_embeddings_async(
                cast(list[str | TextEmbeddingInput], batch), auto_truncate=True
            )
            for batch in batches
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
        import openai

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


# API-based reranking functions (moved from model server)
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


class EmbeddingModel:
    def __init__(
        self,
        server_host: str,  # Changes depending on indexing or inference
        server_port: int,
        model_name: str | None,
        normalize: bool,
        query_prefix: str | None,
        passage_prefix: str | None,
        api_key: str | None,
        api_url: str | None,
        provider_type: EmbeddingProvider | None,
        retrim_content: bool = False,
        callback: IndexingHeartbeatInterface | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        reduced_dimension: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.provider_type = provider_type
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.normalize = normalize
        self.model_name = model_name
        self.retrim_content = retrim_content
        self.api_url = api_url
        self.api_version = api_version
        self.deployment_name = deployment_name
        self.reduced_dimension = reduced_dimension
        self.tokenizer = get_tokenizer(
            model_name=model_name, provider_type=provider_type
        )
        self.callback = callback

        # Only build model server endpoint for local models
        if self.provider_type is None:
            model_server_url = build_model_server_url(server_host, server_port)
            self.embed_server_endpoint: str | None = (
                f"{model_server_url}/encoder/bi-encoder-embed"
            )
        else:
            # API providers don't need model server endpoint
            self.embed_server_endpoint = None

    async def _make_direct_api_call(
        self,
        embed_request: EmbedRequest,
        tenant_id: str | None = None,
        request_id: str | None = None,
    ) -> EmbedResponse:
        """Make direct API call to cloud provider, bypassing model server."""
        if self.provider_type is None:
            raise ValueError("Provider type is required for direct API calls")

        if self.api_key is None:
            logger.error("API key not provided for cloud model")
            raise RuntimeError("API key not provided for cloud model")

        # Check for prefix usage with cloud models
        if embed_request.manual_query_prefix or embed_request.manual_passage_prefix:
            logger.warning("Prefix provided for cloud model, which is not supported")
            raise ValueError(
                "Prefix string is not valid for cloud models. Cloud models take an explicit text type instead."
            )

        if not all(embed_request.texts):
            logger.error("Empty strings provided for embedding")
            raise ValueError("Empty strings are not allowed for embedding.")

        if not embed_request.texts:
            logger.error("No texts provided for embedding")
            raise ValueError("No texts provided for embedding.")

        start_time = time.monotonic()
        total_chars = sum(len(text) for text in embed_request.texts)

        logger.info(
            f"Embedding {len(embed_request.texts)} texts with {total_chars} total characters with provider: {self.provider_type}"
        )

        async with CloudEmbedding(
            api_key=self.api_key,
            provider=self.provider_type,
            api_url=self.api_url,
            api_version=self.api_version,
        ) as cloud_model:
            embeddings = await cloud_model.embed(
                texts=embed_request.texts,
                model_name=embed_request.model_name,
                deployment_name=embed_request.deployment_name,
                text_type=embed_request.text_type,
                reduced_dimension=embed_request.reduced_dimension,
            )

        if any(embedding is None for embedding in embeddings):
            error_message = "Embeddings contain None values\n"
            error_message += "Corresponding texts:\n"
            error_message += "\n".join(embed_request.texts)
            logger.error(error_message)
            raise ValueError(error_message)

        elapsed = time.monotonic() - start_time
        logger.info(
            f"event=embedding_provider "
            f"texts={len(embed_request.texts)} "
            f"chars={total_chars} "
            f"provider={self.provider_type} "
            f"elapsed={elapsed:.2f}"
        )

        return EmbedResponse(embeddings=embeddings)

    def _make_model_server_request(
        self,
        embed_request: EmbedRequest,
        tenant_id: str | None = None,
        request_id: str | None = None,
    ) -> EmbedResponse:
        if self.embed_server_endpoint is None:
            raise ValueError("Model server endpoint is not configured for local models")

        # Store the endpoint in a local variable to help mypy understand it's not None
        endpoint = self.embed_server_endpoint

        def _make_request() -> Response:
            headers = {}
            if tenant_id:
                headers["X-Onyx-Tenant-ID"] = tenant_id

            if request_id:
                headers["X-Onyx-Request-ID"] = request_id

            response = requests.post(
                endpoint,
                headers=headers,
                json=embed_request.model_dump(),
            )
            # signify that this is a rate limit error
            if response.status_code == 429:
                raise ModelServerRateLimitError(response.text)

            response.raise_for_status()
            return response

        final_make_request_func = _make_request

        # if the text type is a passage, add some default
        # retries + handling for rate limiting
        if embed_request.text_type == EmbedTextType.PASSAGE:
            final_make_request_func = retry(
                tries=3,
                delay=5,
                exceptions=(RequestException, ValueError, JSONDecodeError),
            )(final_make_request_func)
            # use 10 second delay as per Azure suggestion
            final_make_request_func = retry(
                tries=10, delay=10, exceptions=ModelServerRateLimitError
            )(final_make_request_func)

        response: Response | None = None

        try:
            response = final_make_request_func()
            return EmbedResponse(**response.json())
        except requests.HTTPError as e:
            if not response:
                raise HTTPError("HTTP error occurred - response is None.") from e

            try:
                error_detail = response.json().get("detail", str(e))
            except Exception:
                error_detail = response.text
            raise HTTPError(f"HTTP error occurred: {error_detail}") from e
        except requests.RequestException as e:
            raise HTTPError(f"Request failed: {str(e)}") from e

    def _batch_encode_texts(
        self,
        texts: list[str],
        text_type: EmbedTextType,
        batch_size: int,
        max_seq_length: int,
        num_threads: int = INDEXING_EMBEDDING_MODEL_NUM_THREADS,
        tenant_id: str | None = None,
        request_id: str | None = None,
    ) -> list[Embedding]:
        text_batches = batch_list(texts, batch_size)

        logger.debug(f"Encoding {len(texts)} texts in {len(text_batches)} batches")

        embeddings: list[Embedding] = []

        def process_batch(
            batch_idx: int,
            batch_len: int,
            text_batch: list[str],
            tenant_id: str | None = None,
            request_id: str | None = None,
        ) -> tuple[int, list[Embedding]]:
            if self.callback:
                if self.callback.should_stop():
                    raise ConnectorStopSignal(
                        "_batch_encode_texts detected stop signal"
                    )

            embed_request = EmbedRequest(
                model_name=self.model_name,
                texts=text_batch,
                api_version=self.api_version,
                deployment_name=self.deployment_name,
                max_context_length=max_seq_length,
                normalize_embeddings=self.normalize,
                api_key=self.api_key,
                provider_type=self.provider_type,
                text_type=text_type,
                manual_query_prefix=self.query_prefix,
                manual_passage_prefix=self.passage_prefix,
                api_url=self.api_url,
                reduced_dimension=self.reduced_dimension,
            )

            start_time = time.monotonic()

            # Route between direct API calls and model server calls
            if self.provider_type is not None:
                # For API providers, make direct API call
                loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(loop)
                    response = loop.run_until_complete(
                        self._make_direct_api_call(
                            embed_request, tenant_id=tenant_id, request_id=request_id
                        )
                    )
                finally:
                    loop.close()
            else:
                # For local models, use model server
                response = self._make_model_server_request(
                    embed_request, tenant_id=tenant_id, request_id=request_id
                )

            end_time = time.monotonic()

            processing_time = end_time - start_time
            logger.debug(
                f"EmbeddingModel.process_batch: Batch {batch_idx}/{batch_len} processing time: {processing_time:.2f} seconds"
            )

            return batch_idx, response.embeddings

        # only multi thread if:
        #   1. num_threads is greater than 1
        #   2. we are using an API-based embedding model (provider_type is not None)
        #   3. there are more than 1 batch (no point in threading if only 1)
        if num_threads >= 1 and self.provider_type and len(text_batches) > 1:
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                future_to_batch = {
                    executor.submit(
                        partial(
                            process_batch,
                            idx,
                            len(text_batches),
                            batch,
                            tenant_id=tenant_id,
                            request_id=request_id,
                        )
                    ): idx
                    for idx, batch in enumerate(text_batches, start=1)
                }

                # Collect results in order
                batch_results: list[tuple[int, list[Embedding]]] = []
                for future in as_completed(future_to_batch):
                    try:
                        result = future.result()
                        batch_results.append(result)
                    except Exception as e:
                        logger.exception("Embedding model failed to process batch")
                        raise e

                # Sort by batch index and extend embeddings
                batch_results.sort(key=lambda x: x[0])
                for _, batch_embeddings in batch_results:
                    embeddings.extend(batch_embeddings)
        else:
            # Original sequential processing
            for idx, text_batch in enumerate(text_batches, start=1):
                _, batch_embeddings = process_batch(
                    idx,
                    len(text_batches),
                    text_batch,
                    tenant_id=tenant_id,
                    request_id=request_id,
                )
                embeddings.extend(batch_embeddings)

        return embeddings

    def encode(
        self,
        texts: list[str],
        text_type: EmbedTextType,
        large_chunks_present: bool = False,
        local_embedding_batch_size: int = BATCH_SIZE_ENCODE_CHUNKS,
        api_embedding_batch_size: int = BATCH_SIZE_ENCODE_CHUNKS_FOR_API_EMBEDDING_SERVICES,
        max_seq_length: int = DOC_EMBEDDING_CONTEXT_SIZE,
        tenant_id: str | None = None,
        request_id: str | None = None,
    ) -> list[Embedding]:
        if not texts or not all(texts):
            raise ValueError(f"Empty or missing text for embedding: {texts}")

        if large_chunks_present:
            max_seq_length *= LARGE_CHUNK_RATIO

        if self.retrim_content:
            # This is applied during indexing as a catchall for overly long titles (or other uncapped fields)
            # Note that this uses just the default tokenizer which may also lead to very minor miscountings
            # However this slight miscounting is very unlikely to have any material impact.
            texts = [
                tokenizer_trim_content(
                    content=text,
                    desired_length=max_seq_length,
                    tokenizer=self.tokenizer,
                )
                for text in texts
            ]

        batch_size = (
            api_embedding_batch_size
            if self.provider_type
            else local_embedding_batch_size
        )

        return self._batch_encode_texts(
            texts=texts,
            text_type=text_type,
            batch_size=batch_size,
            max_seq_length=max_seq_length,
            tenant_id=tenant_id,
            request_id=request_id,
        )

    @classmethod
    def from_db_model(
        cls,
        search_settings: SearchSettings,
        server_host: str,  # Changes depending on indexing or inference
        server_port: int,
        retrim_content: bool = False,
    ) -> "EmbeddingModel":
        return cls(
            server_host=server_host,
            server_port=server_port,
            model_name=search_settings.model_name,
            normalize=search_settings.normalize,
            query_prefix=search_settings.query_prefix,
            passage_prefix=search_settings.passage_prefix,
            api_key=search_settings.api_key,
            provider_type=search_settings.provider_type,
            api_url=search_settings.api_url,
            retrim_content=retrim_content,
            api_version=search_settings.api_version,
            deployment_name=search_settings.deployment_name,
            reduced_dimension=search_settings.reduced_dimension,
        )


class RerankingModel:
    def __init__(
        self,
        model_name: str,
        provider_type: RerankerProvider | None,
        api_key: str | None,
        api_url: str | None,
        model_server_host: str = MODEL_SERVER_HOST,
        model_server_port: int = MODEL_SERVER_PORT,
    ) -> None:
        self.model_name = model_name
        self.provider_type = provider_type
        self.api_key = api_key
        self.api_url = api_url

        # Only build model server endpoint for local models
        if self.provider_type is None:
            model_server_url = build_model_server_url(
                model_server_host, model_server_port
            )
            self.rerank_server_endpoint: str | None = (
                model_server_url + "/encoder/cross-encoder-scores"
            )
        else:
            # API providers don't need model server endpoint
            self.rerank_server_endpoint = None

    async def _make_direct_rerank_call(
        self, query: str, passages: list[str]
    ) -> list[float]:
        """Make direct API call to cloud provider, bypassing model server."""
        if self.provider_type is None:
            raise ValueError("Provider type is required for direct API calls")

        if self.api_key is None:
            raise ValueError("API key is required for cloud provider")

        if self.provider_type == RerankerProvider.COHERE:
            return await cohere_rerank_api(
                query, passages, self.model_name, self.api_key
            )
        elif self.provider_type == RerankerProvider.BEDROCK:
            aws_access_key_id, aws_secret_access_key, aws_region = pass_aws_key(
                self.api_key
            )
            return await cohere_rerank_aws(
                query,
                passages,
                self.model_name,
                aws_region,
                aws_access_key_id,
                aws_secret_access_key,
            )
        elif self.provider_type == RerankerProvider.LITELLM:
            if self.api_url is None:
                raise ValueError("API URL is required for LiteLLM reranking.")
            return await litellm_rerank(
                query, passages, self.api_url, self.model_name, self.api_key
            )
        else:
            raise ValueError(f"Unsupported reranking provider: {self.provider_type}")

    def predict(self, query: str, passages: list[str]) -> list[float]:
        # Route between direct API calls and model server calls
        if self.provider_type is not None:
            # For API providers, make direct API call
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(
                    self._make_direct_rerank_call(query, passages)
                )
            finally:
                loop.close()
        else:
            # For local models, use model server
            if self.rerank_server_endpoint is None:
                raise ValueError(
                    "Rerank server endpoint is not configured for local models"
                )

            rerank_request = RerankRequest(
                query=query,
                documents=passages,
                model_name=self.model_name,
                provider_type=self.provider_type,
                api_key=self.api_key,
                api_url=self.api_url,
            )

            response = requests.post(
                self.rerank_server_endpoint, json=rerank_request.model_dump()
            )
            response.raise_for_status()

            return RerankResponse(**response.json()).scores


class QueryAnalysisModel:
    def __init__(
        self,
        model_server_host: str = MODEL_SERVER_HOST,
        model_server_port: int = MODEL_SERVER_PORT,
        # Lean heavily towards not throwing out keywords
        keyword_percent_threshold: float = 0.1,
        # Lean towards semantic which is the default
        semantic_percent_threshold: float = 0.4,
    ) -> None:
        model_server_url = build_model_server_url(model_server_host, model_server_port)
        self.intent_server_endpoint = model_server_url + "/custom/query-analysis"
        self.keyword_percent_threshold = keyword_percent_threshold
        self.semantic_percent_threshold = semantic_percent_threshold

    def predict(
        self,
        query: str,
    ) -> tuple[bool, list[str]]:
        intent_request = IntentRequest(
            query=query,
            keyword_percent_threshold=self.keyword_percent_threshold,
            semantic_percent_threshold=self.semantic_percent_threshold,
        )

        response = requests.post(
            self.intent_server_endpoint, json=intent_request.model_dump()
        )
        response.raise_for_status()

        response_model = IntentResponse(**response.json())

        return response_model.is_keyword, response_model.keywords


class InformationContentClassificationModel:
    def __init__(
        self,
        model_server_host: str = INDEXING_MODEL_SERVER_HOST,
        model_server_port: int = INDEXING_MODEL_SERVER_PORT,
    ) -> None:
        model_server_url = build_model_server_url(model_server_host, model_server_port)
        self.content_server_endpoint = (
            model_server_url + "/custom/content-classification"
        )

    def predict(
        self,
        queries: list[str],
    ) -> list[ContentClassificationPrediction]:
        response = requests.post(self.content_server_endpoint, json=queries)
        response.raise_for_status()

        model_responses = InformationContentClassificationResponses(
            information_content_classifications=response.json()
        )

        return model_responses.information_content_classifications


class ConnectorClassificationModel:
    def __init__(
        self,
        model_server_host: str = MODEL_SERVER_HOST,
        model_server_port: int = MODEL_SERVER_PORT,
    ):
        model_server_url = build_model_server_url(model_server_host, model_server_port)
        self.connector_classification_endpoint = (
            model_server_url + "/custom/connector-classification"
        )

    def predict(
        self,
        query: str,
        available_connectors: list[str],
    ) -> list[str]:
        connector_classification_request = ConnectorClassificationRequest(
            available_connectors=available_connectors,
            query=query,
        )
        response = requests.post(
            self.connector_classification_endpoint,
            json=connector_classification_request.dict(),
        )
        response.raise_for_status()

        response_model = ConnectorClassificationResponse(**response.json())

        return response_model.connectors


def warm_up_retry(
    func: Callable[..., Any],
    tries: int = 20,
    delay: int = 5,
    *args: Any,
    **kwargs: Any,
) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        exceptions = []
        for attempt in range(tries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                exceptions.append(e)
                logger.info(
                    f"Attempt {attempt + 1}/{tries} failed; retrying in {delay} seconds..."
                )
                time.sleep(delay)
        raise Exception(f"All retries failed: {exceptions}")

    return wrapper


def warm_up_bi_encoder(
    embedding_model: EmbeddingModel,
    non_blocking: bool = False,
) -> None:
    if SKIP_WARM_UP:
        return

    warm_up_str = " ".join(WARM_UP_STRINGS)

    logger.debug(f"Warming up encoder model: {embedding_model.model_name}")
    get_tokenizer(
        model_name=embedding_model.model_name,
        provider_type=embedding_model.provider_type,
    ).encode(warm_up_str)

    def _warm_up() -> None:
        try:
            embedding_model.encode(texts=[warm_up_str], text_type=EmbedTextType.QUERY)
            logger.debug(
                f"Warm-up complete for encoder model: {embedding_model.model_name}"
            )
        except Exception as e:
            logger.warning(
                f"Warm-up request failed for encoder model {embedding_model.model_name}: {e}"
            )

    if non_blocking:
        threading.Thread(target=_warm_up, daemon=True).start()
        logger.debug(
            f"Started non-blocking warm-up for encoder model: {embedding_model.model_name}"
        )
    else:
        retry_encode = warm_up_retry(embedding_model.encode)
        retry_encode(texts=[warm_up_str], text_type=EmbedTextType.QUERY)


def warm_up_cross_encoder(
    rerank_model_name: str,
    non_blocking: bool = False,
) -> None:
    if SKIP_WARM_UP:
        return

    logger.debug(f"Warming up reranking model: {rerank_model_name}")

    reranking_model = RerankingModel(
        model_name=rerank_model_name,
        provider_type=None,
        api_url=None,
        api_key=None,
    )

    def _warm_up() -> None:
        try:
            reranking_model.predict(WARM_UP_STRINGS[0], WARM_UP_STRINGS[1:])
            logger.debug(f"Warm-up complete for reranking model: {rerank_model_name}")
        except Exception as e:
            logger.warning(
                f"Warm-up request failed for reranking model {rerank_model_name}: {e}"
            )

    if non_blocking:
        threading.Thread(target=_warm_up, daemon=True).start()
        logger.debug(
            f"Started non-blocking warm-up for reranking model: {rerank_model_name}"
        )
    else:
        retry_rerank = warm_up_retry(reranking_model.predict)
        retry_rerank(WARM_UP_STRINGS[0], WARM_UP_STRINGS[1:])
