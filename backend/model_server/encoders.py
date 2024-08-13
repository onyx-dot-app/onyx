import gc
import json
from typing import Any
from typing import Optional

import openai
import vertexai  # type: ignore
import voyageai  # type: ignore
from cohere import Client as CohereClient
from fastapi import APIRouter
from fastapi import HTTPException
from google.oauth2 import service_account  # type: ignore
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
from model_server.constants import MODEL_WARM_UP_STRING
from model_server.utils import simple_log_function_time
from shared_configs.configs import CROSS_EMBED_CONTEXT_SIZE
from shared_configs.configs import CROSS_ENCODER_MODEL_ENSEMBLE
from shared_configs.configs import INDEXING_ONLY
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import Embedding
from shared_configs.model_server_models import EmbedRequest
from shared_configs.model_server_models import EmbedResponse
from shared_configs.model_server_models import RerankRequest
from shared_configs.model_server_models import RerankResponse


logger = setup_logger()

router = APIRouter(prefix="/encoder")

_GLOBAL_MODELS_DICT: dict[str, "SentenceTransformer"] = {}
_RERANK_MODELS: Optional[list["CrossEncoder"]] = None
# If we are not only indexing, dont want retry very long
_RETRY_DELAY = 10 if INDEXING_ONLY else 0.1
_RETRY_TRIES = 10 if INDEXING_ONLY else 2


def _initialize_client(
    api_key: str, provider: EmbeddingProvider, model: str | None = None
) -> Any:
    if provider == EmbeddingProvider.OPENAI:
        return openai.OpenAI(api_key=api_key)
    elif provider == EmbeddingProvider.COHERE:
        return CohereClient(api_key=api_key)
    elif provider == EmbeddingProvider.VOYAGE:
        return voyageai.Client(api_key=api_key)
    elif provider == EmbeddingProvider.GOOGLE:
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(api_key)
        )
        project_id = json.loads(api_key)["project_id"]
        vertexai.init(project=project_id, credentials=credentials)
        return TextEmbeddingModel.from_pretrained(model or DEFAULT_VERTEX_MODEL)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


class CloudEmbedding:
    def __init__(
        self,
        api_key: str,
        provider: str,
        # Only for Google as is needed on client setup
        model: str | None = None,
    ) -> None:
        try:
            self.provider = EmbeddingProvider(provider.lower())
        except ValueError:
            raise ValueError(f"Unsupported provider: {provider}")
        self.client = _initialize_client(api_key, self.provider, model)

    def _embed_openai(self, texts: list[str], model: str | None) -> list[Embedding]:
        if model is None:
            model = DEFAULT_OPENAI_MODEL

        # OpenAI does not seem to provide truncation option, however
        # the context lengths used by Danswer currently are smaller than the max token length
        # for OpenAI embeddings so it's not a big deal
        try:
            response = self.client.embeddings.create(input=texts, model=model)
            return [embedding.embedding for embedding in response.data]
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
        if model is None:
            model = DEFAULT_COHERE_MODEL

        # Does not use the same tokenizer as the Danswer API server but it's approximately the same
        # empirically it's only off by a very few tokens so it's not a big deal
        response = self.client.embed(
            texts=texts,
            model=model,
            input_type=embedding_type,
            truncate="END",
        )
        return response.embeddings

    def _embed_voyage(
        self, texts: list[str], model: str | None, embedding_type: str
    ) -> list[Embedding]:
        if model is None:
            model = DEFAULT_VOYAGE_MODEL

        # Similar to Cohere, the API server will do approximate size chunking
        # it's acceptable to miss by a few tokens
        response = self.client.embed(
            texts,
            model=model,
            input_type=embedding_type,
            truncation=True,  # Also this is default
        )
        return response.embeddings

    def _embed_vertex(
        self, texts: list[str], model: str | None, embedding_type: str
    ) -> list[Embedding]:
        if model is None:
            model = DEFAULT_VERTEX_MODEL

        embeddings = self.client.get_embeddings(
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

    @retry(tries=_RETRY_TRIES, delay=_RETRY_DELAY)
    def embed(
        self,
        *,
        texts: list[str],
        text_type: EmbedTextType,
        model_name: str | None = None,
    ) -> list[Embedding]:
        try:
            if self.provider == EmbeddingProvider.OPENAI:
                return self._embed_openai(texts, model_name)

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
        api_key: str, provider: str, model: str | None = None
    ) -> "CloudEmbedding":
        logger.debug(f"Creating Embedding instance for provider: {provider}")
        return CloudEmbedding(api_key, provider, model)


def get_embedding_model(
    model_name: str,
    max_context_length: int,
) -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer  # type: ignore

    global _GLOBAL_MODELS_DICT  # A dictionary to store models

    if _GLOBAL_MODELS_DICT is None:
        _GLOBAL_MODELS_DICT = {}

    if model_name not in _GLOBAL_MODELS_DICT:
        logger.info(f"Loading {model_name}")
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


def get_local_reranking_model_ensemble(
    model_names: list[str] = CROSS_ENCODER_MODEL_ENSEMBLE,
    max_context_length: int = CROSS_EMBED_CONTEXT_SIZE,
) -> list[CrossEncoder]:
    global _RERANK_MODELS
    if _RERANK_MODELS is None or max_context_length != _RERANK_MODELS[0].max_length:
        del _RERANK_MODELS
        gc.collect()

        _RERANK_MODELS = []
        for model_name in model_names:
            logger.info(f"Loading {model_name}")
            model = CrossEncoder(model_name)
            model.max_length = max_context_length
            _RERANK_MODELS.append(model)
    return _RERANK_MODELS


def warm_up_cross_encoders() -> None:
    logger.info(f"Warming up Cross-Encoders: {CROSS_ENCODER_MODEL_ENSEMBLE}")

    cross_encoders = get_local_reranking_model_ensemble()
    [
        cross_encoder.predict((MODEL_WARM_UP_STRING, MODEL_WARM_UP_STRING))
        for cross_encoder in cross_encoders
    ]


@simple_log_function_time()
def embed_text(
    texts: list[str],
    text_type: EmbedTextType,
    model_name: str | None,
    max_context_length: int,
    normalize_embeddings: bool,
    api_key: str | None,
    provider_type: str | None,
    prefix: str | None,
) -> list[Embedding]:
    if not all(texts):
        raise ValueError("Empty strings are not allowed for embedding.")

    # Third party API based embedding model
    if not texts:
        raise ValueError("No texts provided for embedding.")
    elif provider_type is not None:
        logger.debug(f"Embedding text with provider: {provider_type}")
        if api_key is None:
            raise RuntimeError("API key not provided for cloud model")

        if prefix:
            # This may change in the future if some providers require the user
            # to manually append a prefix but this is not the case currently
            raise ValueError(
                "Prefix string is not valid for cloud models. "
                "Cloud models take an explicit text type instead."
            )

        cloud_model = CloudEmbedding(
            api_key=api_key, provider=provider_type, model=model_name
        )
        embeddings = cloud_model.embed(
            texts=texts,
            model_name=model_name,
            text_type=text_type,
        )

        # Check for None values in embeddings
        if any(embedding is None for embedding in embeddings):
            error_message = "Embeddings contain None values\n"
            error_message += "Corresponding texts:\n"
            error_message += "\n".join(texts)
            raise ValueError(error_message)

    elif model_name is not None:
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
        raise ValueError(
            "Either model name or provider must be provided to run embeddings."
        )

    return embeddings


@simple_log_function_time()
def calc_sim_scores(query: str, docs: list[str]) -> list[list[float] | None]:
    cross_encoders = get_local_reranking_model_ensemble()
    sim_scores = [
        encoder.predict([(query, doc) for doc in docs]).tolist()  # type: ignore
        for encoder in cross_encoders
    ]
    return sim_scores


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
            max_context_length=embed_request.max_context_length,
            normalize_embeddings=embed_request.normalize_embeddings,
            api_key=embed_request.api_key,
            provider_type=embed_request.provider_type,
            text_type=embed_request.text_type,
            prefix=prefix,
        )
        return EmbedResponse(embeddings=embeddings)
    except Exception as e:
        exception_detail = f"Error during embedding process:\n{str(e)}"
        logger.exception(exception_detail)
        raise HTTPException(status_code=500, detail=exception_detail)


@router.post("/cross-encoder-scores")
async def process_rerank_request(embed_request: RerankRequest) -> RerankResponse:
    """Cross encoders can be purely black box from the app perspective"""
    if INDEXING_ONLY:
        raise RuntimeError("Indexing model server should not call intent endpoint")

    if not embed_request.documents or not embed_request.query:
        raise HTTPException(
            status_code=400, detail="Missing documents or query for reranking"
        )
    if not all(embed_request.documents):
        raise ValueError("Empty documents cannot be reranked.")

    try:
        sim_scores = calc_sim_scores(
            query=embed_request.query, docs=embed_request.documents
        )
        return RerankResponse(scores=sim_scores)
    except Exception as e:
        logger.exception(f"Error during reranking process:\n{str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to run Cross-Encoder reranking"
        )
