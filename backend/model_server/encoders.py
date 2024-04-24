import gc
from typing import Optional

from fastapi import APIRouter
from fastapi import HTTPException
from sentence_transformers import CrossEncoder  # type: ignore
from sentence_transformers import SentenceTransformer  # type: ignore

from danswer.utils.logger import setup_logger
from model_server.constants import MODEL_WARM_UP_STRING
from model_server.utils import simple_log_function_time
from shared_configs.configs import CROSS_EMBED_CONTEXT_SIZE
from shared_configs.configs import CROSS_ENCODER_MODEL_ENSEMBLE
from shared_configs.configs import INDEXING_ONLY
from shared_configs.model_server_models import EmbedRequest
from shared_configs.model_server_models import EmbedResponse
from shared_configs.model_server_models import RerankRequest
from shared_configs.model_server_models import RerankResponse

logger = setup_logger()

router = APIRouter(prefix="/encoder")

_GLOBAL_MODELS_DICT: dict[str, "SentenceTransformer"] = {}
_RERANK_MODELS: Optional[list["CrossEncoder"]] = None


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
        model = SentenceTransformer(model_name)
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
    model_name: str,
    max_context_length: int,
    normalize_embeddings: bool,
) -> list[list[float]]:
    model = get_embedding_model(
        model_name=model_name, max_context_length=max_context_length
    )
    embeddings = model.encode(texts, normalize_embeddings=normalize_embeddings)

    if not isinstance(embeddings, list):
        embeddings = embeddings.tolist()

    return embeddings


@simple_log_function_time()
def calc_sim_scores(query: str, docs: list[str]) -> list[list[float]]:
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
    try:
        embeddings = embed_text(
            texts=embed_request.texts,
            model_name=embed_request.model_name,
            max_context_length=embed_request.max_context_length,
            normalize_embeddings=embed_request.normalize_embeddings,
        )
        return EmbedResponse(embeddings=embeddings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cross-encoder-scores")
async def process_rerank_request(embed_request: RerankRequest) -> RerankResponse:
    """Cross encoders can be purely black box from the app perspective"""
    if INDEXING_ONLY:
        raise RuntimeError("Indexing model server should not call intent endpoint")

    try:
        sim_scores = calc_sim_scores(
            query=embed_request.query, docs=embed_request.documents
        )
        return RerankResponse(scores=sim_scores)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
