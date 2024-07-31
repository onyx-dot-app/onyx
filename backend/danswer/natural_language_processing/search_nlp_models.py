import time

import requests
from httpx import HTTPError

from danswer.configs.model_configs import BATCH_SIZE_ENCODE_CHUNKS
from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.db.models import EmbeddingModel as DBEmbeddingModel
from danswer.natural_language_processing.utils import get_tokenizer
from danswer.natural_language_processing.utils import tokenizer_trim_content
from danswer.utils.batching import batch_list
from danswer.utils.logger import setup_logger
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import Embedding
from shared_configs.model_server_models import EmbedRequest
from shared_configs.model_server_models import EmbedResponse
from shared_configs.model_server_models import IntentRequest
from shared_configs.model_server_models import IntentResponse
from shared_configs.model_server_models import RerankRequest
from shared_configs.model_server_models import RerankResponse

from tenacity import retry, stop_after_attempt, wait_exponential

logger = setup_logger()


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
        provider_type: str | None,
        # The following are globals are currently not configurable
        max_seq_length: int = DOC_EMBEDDING_CONTEXT_SIZE,
        retrim_content: bool = False,
    ) -> None:
        self.api_key = api_key
        self.provider_type = provider_type
        self.max_seq_length = max_seq_length
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.normalize = normalize
        self.model_name = model_name
        self.retrim_content = retrim_content

        model_server_url = build_model_server_url(server_host, server_port)
        self.embed_server_endpoint = f"{model_server_url}/encoder/bi-encoder-embed"

    @retry(wait=wait_exponential(), stop=stop_after_attempt(3))
    def encode(
        self,
        texts: list[str],
        text_type: EmbedTextType,
        batch_size: int = BATCH_SIZE_ENCODE_CHUNKS,
    ) -> list[Embedding]:
        if not texts or not all(texts):
            raise ValueError(f"Empty or missing text for embedding: {texts}")

        if self.retrim_content:
            # This is applied during indexing as a catchall for overly long titles (or other uncapped fields)
            # Note that this uses just the default tokenizer which may also lead to very minor miscountings
            # However this slight miscounting is very unlikely to have any material impact.
            texts = [
                tokenizer_trim_content(
                    content=text,
                    desired_length=self.max_seq_length,
                    tokenizer=get_tokenizer(
                        model_name=self.model_name,
                        provider_type=self.provider_type,
                    ),
                )
                for text in texts
            ]

        if self.provider_type:
            embed_request = EmbedRequest(
                model_name=self.model_name,
                texts=texts,
                max_context_length=self.max_seq_length,
                normalize_embeddings=self.normalize,
                api_key=self.api_key,
                provider_type=self.provider_type,
                text_type=text_type,
                manual_query_prefix=self.query_prefix,
                manual_passage_prefix=self.passage_prefix,
            )
            response = requests.post(
                self.embed_server_endpoint, json=embed_request.dict()
            )
            try:
                response.raise_for_status()
            except requests.HTTPError as e:
                error_detail = response.json().get("detail", str(e))
                raise HTTPError(f"HTTP error occurred: {error_detail}") from e
            except requests.RequestException as e:
                raise HTTPError(f"Request failed: {str(e)}") from e

            return EmbedResponse(**response.json()).embeddings

        # Batching for local embedding
        text_batches = batch_list(texts, batch_size)
        embeddings: list[Embedding] = []
        logger.debug(
            f"Encoding {len(texts)} texts in {len(text_batches)} batches for local model"
        )
        for idx, text_batch in enumerate(text_batches, start=1):
            logger.debug(f"Encoding batch {idx} of {len(text_batches)}")
            embed_request = EmbedRequest(
                model_name=self.model_name,
                texts=text_batch,
                max_context_length=self.max_seq_length,
                normalize_embeddings=self.normalize,
                api_key=self.api_key,
                provider_type=self.provider_type,
                text_type=text_type,
                manual_query_prefix=self.query_prefix,
                manual_passage_prefix=self.passage_prefix,
            )

            response = requests.post(
                self.embed_server_endpoint, json=embed_request.dict()
            )
            try:
                response.raise_for_status()
            except requests.HTTPError as e:
                error_detail = response.json().get("detail", str(e))
                raise HTTPError(f"HTTP error occurred: {error_detail}") from e
            except requests.RequestException as e:
                raise HTTPError(f"Request failed: {str(e)}") from e
            # Normalize embeddings is only configured via model_configs.py, be sure to use right
            # value for the set loss
            embeddings.extend(EmbedResponse(**response.json()).embeddings)
        return embeddings


class CrossEncoderEnsembleModel:
    def __init__(
        self,
        model_server_host: str = MODEL_SERVER_HOST,
        model_server_port: int = MODEL_SERVER_PORT,
    ) -> None:
        model_server_url = build_model_server_url(model_server_host, model_server_port)
        self.rerank_server_endpoint = model_server_url + "/encoder/cross-encoder-scores"

    def predict(self, query: str, passages: list[str]) -> list[list[float] | None]:
        rerank_request = RerankRequest(query=query, documents=passages)

        response = requests.post(
            self.rerank_server_endpoint, json=rerank_request.dict()
        )
        response.raise_for_status()

        return RerankResponse(**response.json()).scores


class IntentModel:
    def __init__(
        self,
        model_server_host: str = MODEL_SERVER_HOST,
        model_server_port: int = MODEL_SERVER_PORT,
    ) -> None:
        model_server_url = build_model_server_url(model_server_host, model_server_port)
        self.intent_server_endpoint = model_server_url + "/custom/intent-model"

    def predict(
        self,
        query: str,
    ) -> list[float]:
        intent_request = IntentRequest(query=query)

        response = requests.post(
            self.intent_server_endpoint, json=intent_request.dict()
        )
        response.raise_for_status()

        return IntentResponse(**response.json()).class_probs


def warm_up_encoders(
    embedding_model: DBEmbeddingModel,
    model_server_host: str = MODEL_SERVER_HOST,
    model_server_port: int = MODEL_SERVER_PORT,
) -> None:
    model_name = embedding_model.model_name
    normalize = embedding_model.normalize
    provider_type = embedding_model.provider_type
    warm_up_str = (
        "Danswer is amazing! Check out our easy deployment guide at "
        "https://docs.danswer.dev/quickstart"
    )

    # May not be the exact same tokenizer used for the indexing flow
    logger.info(f"Warming up encoder model: {model_name}")
    get_tokenizer(model_name=model_name, provider_type=provider_type).encode(
        warm_up_str
    )

    embed_model = EmbeddingModel(
        model_name=model_name,
        normalize=normalize,
        provider_type=provider_type,
        # Not a big deal if prefix is incorrect
        query_prefix=None,
        passage_prefix=None,
        server_host=model_server_host,
        server_port=model_server_port,
        api_key=None,
    )

    # First time downloading the models it may take even longer, but just in case,
    # retry the whole server
    wait_time = 5
    for _ in range(20):
        try:
            embed_model.encode(texts=[warm_up_str], text_type=EmbedTextType.QUERY)
            return
        except Exception:
            logger.exception(
                f"Failed to run test embedding, retrying in {wait_time} seconds..."
            )
            time.sleep(wait_time)
    raise Exception("Failed to run test embedding.")
