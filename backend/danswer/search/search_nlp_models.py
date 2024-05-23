import gc
import os
import time
from typing import Optional
from typing import TYPE_CHECKING

import requests
from transformers import logging as transformer_logging  # type:ignore

from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.configs.model_configs import DOCUMENT_ENCODER_MODEL
from danswer.search.enums import EmbedTextType
from danswer.utils.logger import setup_logger
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.model_server_models import EmbedRequest
from shared_configs.model_server_models import EmbedResponse
from shared_configs.model_server_models import IntentRequest
from shared_configs.model_server_models import IntentResponse
from shared_configs.model_server_models import RerankRequest
from shared_configs.model_server_models import RerankResponse

transformer_logging.set_verbosity_error()

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

logger = setup_logger()


if TYPE_CHECKING:
    from transformers import AutoTokenizer  # type: ignore


_TOKENIZER: tuple[Optional["AutoTokenizer"], str | None] = (None, None)


def clean_model_name(model_str: str) -> str:
    return model_str.replace("/", "_").replace("-", "_").replace(".", "_")


# NOTE: If None is used, it may not be using the "correct" tokenizer, for cases
# where this is more important, be sure to refresh with the actual model name
def get_default_tokenizer(model_name: str | None = None) -> "AutoTokenizer":
    # NOTE: doing a local import here to avoid reduce memory usage caused by
    # processes importing this file despite not using any of this
    from transformers import AutoTokenizer  # type: ignore

    global _TOKENIZER
    if _TOKENIZER[0] is None or (
        _TOKENIZER[1] is not None and _TOKENIZER[1] != model_name
    ):
        if _TOKENIZER[0] is not None:
            del _TOKENIZER
            gc.collect()

        if model_name is None:
            # This could be inaccurate
            model_name = DOCUMENT_ENCODER_MODEL

        _TOKENIZER = (AutoTokenizer.from_pretrained(model_name), model_name)

        if hasattr(_TOKENIZER[0], "is_fast") and _TOKENIZER[0].is_fast:
            os.environ["TOKENIZERS_PARALLELISM"] = "false"

    return _TOKENIZER[0]


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
        model_name: str,
        query_prefix: str | None,
        passage_prefix: str | None,
        normalize: bool,
        server_host: str,  # Changes depending on indexing or inference
        server_port: int,
        # The following are globals are currently not configurable
        max_seq_length: int = DOC_EMBEDDING_CONTEXT_SIZE,
    ) -> None:
        self.model_name = model_name
        self.max_seq_length = max_seq_length
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.normalize = normalize

        model_server_url = build_model_server_url(server_host, server_port)
        self.embed_server_endpoint = f"{model_server_url}/encoder/bi-encoder-embed"

    def encode(self, texts: list[str], text_type: EmbedTextType) -> list[list[float]]:
        if text_type == EmbedTextType.QUERY and self.query_prefix:
            prefixed_texts = [self.query_prefix + text for text in texts]
        elif text_type == EmbedTextType.PASSAGE and self.passage_prefix:
            prefixed_texts = [self.passage_prefix + text for text in texts]
        else:
            prefixed_texts = texts

        embed_request = EmbedRequest(
            texts=prefixed_texts,
            model_name=self.model_name,
            max_context_length=self.max_seq_length,
            normalize_embeddings=self.normalize,
        )

        response = requests.post(self.embed_server_endpoint, json=embed_request.dict())
        response.raise_for_status()

        return EmbedResponse(**response.json()).embeddings


class CrossEncoderEnsembleModel:
    def __init__(
        self,
        model_server_host: str = MODEL_SERVER_HOST,
        model_server_port: int = MODEL_SERVER_PORT,
    ) -> None:
        model_server_url = build_model_server_url(model_server_host, model_server_port)
        self.rerank_server_endpoint = model_server_url + "/encoder/cross-encoder-scores"

    def predict(self, query: str, passages: list[str]) -> list[list[float]]:
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
    model_name: str,
    normalize: bool,
    model_server_host: str = MODEL_SERVER_HOST,
    model_server_port: int = MODEL_SERVER_PORT,
) -> None:
    warm_up_str = (
        "Danswer is amazing! Check out our easy deployment guide at "
        "https://docs.danswer.dev/quickstart"
    )

    get_default_tokenizer(model_name=model_name)(warm_up_str)

    embed_model = EmbeddingModel(
        model_name=model_name,
        normalize=normalize,
        # Not a big deal if prefix is incorrect
        query_prefix=None,
        passage_prefix=None,
        server_host=model_server_host,
        server_port=model_server_port,
    )

    # First time downloading the models it may take even longer, but just in case,
    # retry the whole server
    wait_time = 5
    for attempt in range(20):
        try:
            embed_model.encode(texts=[warm_up_str], text_type=EmbedTextType.QUERY)
            return
        except Exception:
            logger.exception(
                f"Failed to run test embedding, retrying in {wait_time} seconds..."
            )
            time.sleep(wait_time)
    raise Exception("Failed to run test embedding.")
