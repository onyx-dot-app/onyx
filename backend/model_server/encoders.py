import asyncio
import time
from typing import Any
from typing import Optional

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from litellm.exceptions import RateLimitError
from sentence_transformers import CrossEncoder  # type: ignore
from sentence_transformers import SentenceTransformer  # type: ignore

from model_server.utils import simple_log_function_time
from onyx.utils.logger import setup_logger
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
_RERANK_MODEL: Optional["CrossEncoder"] = None

# If we are not only indexing, dont want retry very long
_RETRY_DELAY = 10 if INDEXING_ONLY else 0.1
_RETRY_TRIES = 10 if INDEXING_ONLY else 2


def get_embedding_model(
    model_name: str,
    max_context_length: int,
) -> "SentenceTransformer":
    """
    Loads or returns a cached SentenceTransformer, sets max_seq_length, pins device,
    pre-warms rotary caches once, and wraps encode() with a lock to avoid cache races.
    """
    from sentence_transformers import SentenceTransformer  # type: ignore
    import torch
    import threading
    import functools

    def _pick_device() -> str:
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _prewarm_rope(st_model: "SentenceTransformer", target_len: int) -> None:
        """
        Build RoPE cos/sin caches once on the final device/dtype so later forwards only read.
        Works by calling the underlying HF model directly with dummy IDs/attention.
        """
        try:
            # Get underlying HF model + tokenizer from the first transformer module
            tfm = st_model[0]  # sentence_transformers.models.Transformer
            hf_model = getattr(tfm, "auto_model", None)
            tok = getattr(tfm, "tokenizer", None)

            if hf_model is None:
                # Fallback: trigger through the ST pipeline (slower, but still builds caches)
                dummy_text = "x " * max(1, target_len - 2)
                st_model.encode(
                    [dummy_text],
                    batch_size=1,
                    convert_to_tensor=True,
                    show_progress_bar=False,
                    normalize_embeddings=False,
                )
                st_model._rope_prewarmed_to = int(target_len)
                return

            # Respect model limits; don't exceed its configured max positions
            conf = getattr(hf_model, "config", None)
            max_pos = getattr(conf, "max_position_embeddings", None)
            L = min(target_len, max_pos) if max_pos else target_len

            pad_id = getattr(conf, "pad_token_id", None)
            if pad_id is None and tok is not None:
                pad_id = tok.pad_token_id
            if pad_id is None:
                pad_id = 0

            device = hf_model.device
            hf_model.eval()
            with torch.inference_mode():
                input_ids = torch.full((1, L), pad_id, dtype=torch.long, device=device)
                attn = torch.ones_like(input_ids)
                _ = hf_model(input_ids=input_ids, attention_mask=attn)

            st_model._rope_prewarmed_to = int(L)
        except Exception as e:
            # Non-fatal: we still have the lock below as a safety net
            try:
                logger.warning(f"RoPE pre-warm skipped/failed: {e}")
            except Exception:
                pass

    def _wrap_encode_with_lock(st_model: "SentenceTransformer") -> None:
        """Serialize encode() to avoid concurrent cache resizes."""
        lock = threading.Lock()
        real_encode = st_model.encode

        @functools.wraps(real_encode)
        def locked_encode(*args, **kwargs):
            with lock:
                return real_encode(*args, **kwargs)

        st_model.encode = locked_encode  # type: ignore[attr-defined]
        st_model._encode_lock = lock  # for debugging/inspection

    global _GLOBAL_MODELS_DICT  # dict[str, SentenceTransformer]

    if model_name not in _GLOBAL_MODELS_DICT:
        logger.notice(f"Loading {model_name}")
        device = _pick_device()
        model = SentenceTransformer(
            model_name_or_path=model_name,
            trust_remote_code=True,
            device=device,  # ensure final device is fixed before pre-warm
        )
        model.max_seq_length = max_context_length

        # Pre-warm once (so RoPE caches are built and stable) and wrap with a lock
        _prewarm_rope(model, max_context_length)
        # _wrap_encode_with_lock(model)

        _GLOBAL_MODELS_DICT[model_name] = model
    else:
        model = _GLOBAL_MODELS_DICT[model_name]
        if max_context_length != model.max_seq_length:
            model.max_seq_length = max_context_length
            # If caller raised the context length above previous pre-warm, rebuild once
            prev = getattr(model, "_rope_prewarmed_to", 0)
            if max_context_length > int(prev or 0):
                _prewarm_rope(model, max_context_length)

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


ENCODING_RETRIES = 3
ENCODING_RETRY_DELAY = 0.1


def _concurrent_embedding(
    texts: list[str], model: "SentenceTransformer", normalize_embeddings: bool
) -> Any:
    """Synchronous wrapper for concurrent_embedding to use with run_in_executor."""
    for _ in range(ENCODING_RETRIES):
        try:
            return model.encode(texts, normalize_embeddings=normalize_embeddings)
        except RuntimeError as e:
            # There is a concurrency bug in the SentenceTransformer library that causes
            # the model to fail to encode texts. It's pretty rare and we want to allow
            # concurrent embedding, hence we retry (the specific error is
            # "RuntimeError: Already borrowed" and occurs in the transformers library)
            logger.error(f"Error encoding texts, retrying: {e}")
            time.sleep(ENCODING_RETRY_DELAY)
    return model.encode(texts, normalize_embeddings=normalize_embeddings)


@simple_log_function_time()
async def embed_text(
    texts: list[str],
    model_name: str | None,
    max_context_length: int,
    normalize_embeddings: bool,
    prefix: str | None,
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

    # Only local models should call this function now
    # API providers should go directly to API server

    if model_name is not None:
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
            lambda: _concurrent_embedding(
                prefixed_texts, local_model, normalize_embeddings
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
        logger.error("Model name not specified for embedding")
        raise ValueError("Model name must be provided to run embeddings.")

    return embeddings


@simple_log_function_time()
async def local_rerank(query: str, docs: list[str], model_name: str) -> list[float]:
    cross_encoder = get_local_reranking_model(model_name)
    # Run CPU-bound reranking in a thread pool
    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: cross_encoder.predict([(query, doc) for doc in docs]).tolist(),  # type: ignore
    )


@router.post("/bi-encoder-embed")
async def route_bi_encoder_embed(
    request: Request,
    embed_request: EmbedRequest,
) -> EmbedResponse:
    return await process_embed_request(embed_request, request.app.state.gpu_type)


async def process_embed_request(
    embed_request: EmbedRequest, gpu_type: str = "UNKNOWN"
) -> EmbedResponse:
    # Only local models should use this endpoint - API providers should make direct API calls
    if embed_request.provider_type is not None:
        raise ValueError(
            f"Model server embedding endpoint should only be used for local models. "
            f"API provider '{embed_request.provider_type}' should make direct API calls instead."
        )

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
            max_context_length=embed_request.max_context_length,
            normalize_embeddings=embed_request.normalize_embeddings,
            prefix=prefix,
            gpu_type=gpu_type,
        )
        return EmbedResponse(embeddings=embeddings)
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
    # Only local models should use this endpoint - API providers should make direct API calls
    if rerank_request.provider_type is not None:
        raise ValueError(
            f"Model server reranking endpoint should only be used for local models. "
            f"API provider '{rerank_request.provider_type}' should make direct API calls instead."
        )

    if INDEXING_ONLY:
        raise RuntimeError("Indexing model server should not call intent endpoint")

    if not rerank_request.documents or not rerank_request.query:
        raise HTTPException(
            status_code=400, detail="Missing documents or query for reranking"
        )
    if not all(rerank_request.documents):
        raise ValueError("Empty documents cannot be reranked.")

    try:
        # At this point, provider_type is None, so handle local reranking
        sim_scores = await local_rerank(
            query=rerank_request.query,
            docs=rerank_request.documents,
            model_name=rerank_request.model_name,
        )
        return RerankResponse(scores=sim_scores)

    except Exception as e:
        logger.exception(f"Error during reranking process:\n{str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to run Cross-Encoder reranking"
        )
