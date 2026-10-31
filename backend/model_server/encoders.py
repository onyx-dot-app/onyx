import asyncio
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request

from model_server.embedding_model_loader import load_embedding_model
from model_server.utils import simple_log_function_time
from onyx.utils.logger import setup_logger
from shared_configs.embedding_models import get_local_model_spec
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import Embedding, EmbedRequest, EmbedResponse

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = setup_logger()

router = APIRouter(prefix="/encoder")


_GLOBAL_MODELS_DICT: dict[str, "SentenceTransformer"] = {}
# The longest sequence that each model's RoPE caches are pre-warmed to.
_ROPE_PREWARMED_TO: dict[str, int] = {}

# One lock per model, so a model loads once even if requests race.
_MODEL_LOCKS: dict[str, threading.Lock] = {}
_MODEL_LOCKS_GUARD = threading.Lock()

# Loads (downloads included) run here, off the event loop. Requests for the same
# model and context length share one job, so requests that wait on a download
# hold no threads.
# Two workers: at most PRESENT + FUTURE weights load at once, which caps memory.
_MODEL_LOAD_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="embedding-model-load"
)
_PENDING_MODEL_JOBS: dict[tuple[str, int], Future["SentenceTransformer"]] = {}
_PENDING_MODEL_JOBS_GUARD = threading.Lock()

# Registry models get room for the query/passage prefix, which the chunker does
# not count, so the prefix does not cut off the end of a full chunk.
REGISTRY_MODEL_PREFIX_HEADROOM_TOKENS = 32


def _model_lock(model_name: str) -> threading.Lock:
    with _MODEL_LOCKS_GUARD:
        lock = _MODEL_LOCKS.get(model_name)
        if lock is None:
            lock = threading.Lock()
            _MODEL_LOCKS[model_name] = lock
        return lock


def _target_max_seq_length(model_name: str, max_context_length: int) -> int:
    if get_local_model_spec(model_name) is not None:
        return max_context_length + REGISTRY_MODEL_PREFIX_HEADROOM_TOKENS
    return max_context_length


def _prewarm_rope(
    model_name: str, st_model: "SentenceTransformer", target_len: int
) -> None:
    """
    Build RoPE cos/sin caches once on the final device/dtype so later forwards only read.
    Works by calling the underlying HF model directly with dummy IDs/attention.
    """
    try:
        # ensure > max seq after tokenization
        # Ideally we would use the saved tokenizer, but whatever it's ok
        # we'll make an assumption about tokenization here
        long_text = "x " * (target_len * 2)
        _ = st_model.encode(
            [long_text],
            batch_size=1,
            convert_to_tensor=True,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
        _ROPE_PREWARMED_TO[model_name] = target_len
        logger.info("RoPE pre-warm successful")
    except Exception as e:
        logger.warning("RoPE pre-warm skipped/failed: %s", e)


def get_embedding_model(
    model_name: str,
    max_context_length: int,
) -> "SentenceTransformer":
    """
    Loads or returns a cached SentenceTransformer, sets max_seq_length and
    pre-warms rotary caches.

    Blocking: a first load can download gigabytes. Async code must use
    `_get_embedding_model_off_loop`.
    """
    max_seq_length = _target_max_seq_length(model_name, max_context_length)

    with _model_lock(model_name):
        model = _GLOBAL_MODELS_DICT.get(model_name)
        if model is None:
            logger.notice("Loading %s", model_name)
            # Raises on failure, so a failed or rejected model is never cached.
            model = load_embedding_model(model_name)
            model.max_seq_length = max_seq_length
            _prewarm_rope(model_name, model, max_seq_length)
            _GLOBAL_MODELS_DICT[model_name] = model
        elif max_seq_length != model.max_seq_length:
            model.max_seq_length = max_seq_length
            # Caches built for a longer sequence also serve a shorter one.
            if max_seq_length > _ROPE_PREWARMED_TO.get(model_name, 0):
                _prewarm_rope(model_name, model, max_seq_length)

    return model


def _forget_model_job(
    job_key: tuple[str, int], job: Future["SentenceTransformer"]
) -> None:
    with _PENDING_MODEL_JOBS_GUARD:
        if _PENDING_MODEL_JOBS.get(job_key) is job:
            del _PENDING_MODEL_JOBS[job_key]


async def _get_embedding_model_off_loop(
    model_name: str, max_context_length: int
) -> "SentenceTransformer":
    """`get_embedding_model` without blocking the event loop."""
    model = _GLOBAL_MODELS_DICT.get(model_name)
    if model is not None and model.max_seq_length == _target_max_seq_length(
        model_name, max_context_length
    ):
        return model

    job_key = (model_name, max_context_length)
    with _PENDING_MODEL_JOBS_GUARD:
        job = _PENDING_MODEL_JOBS.get(job_key)
        is_new_job = job is None
        if job is None:
            job = _MODEL_LOAD_EXECUTOR.submit(
                get_embedding_model, model_name, max_context_length
            )
            _PENDING_MODEL_JOBS[job_key] = job
    if is_new_job:
        # Outside the guard: the callback runs at once if the job is done.
        job.add_done_callback(partial(_forget_model_job, job_key))

    # A cancelled request must not cancel the job that other requests share.
    return await asyncio.shield(asyncio.wrap_future(job))


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
            logger.warning("Error encoding texts, retrying: %s", e)
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
            "Embedding %s texts with %s total characters with local model: %s",
            len(texts),
            total_chars,
            model_name,
        )

        prefixed_texts = [f"{prefix}{text}" for text in texts] if prefix else texts

        local_model = await _get_embedding_model_off_loop(
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
            "Successfully embedded %s texts with %s total characters with local model %s in %s",
            len(texts),
            total_chars,
            model_name,
            format(elapsed, ".2f"),
        )
        logger.info(
            "event=embedding_model texts=%s chars=%s model=%s gpu=%s elapsed=%s",
            len(texts),
            total_chars,
            model_name,
            gpu_type,
            format(elapsed, ".2f"),
        )
    else:
        logger.error("Model name not specified for embedding")
        raise ValueError("Model name must be provided to run embeddings.")

    return embeddings


@router.post("/bi-encoder-embed")
async def route_bi_encoder_embed(
    request: Request,
    embed_request: EmbedRequest,
) -> EmbedResponse:
    return await process_embed_request(embed_request, request.app.state.gpu_type)


async def process_embed_request(
    embed_request: EmbedRequest, gpu_type: str = "UNKNOWN"
) -> EmbedResponse:
    from litellm.exceptions import RateLimitError

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
            "Error during embedding process: provider=%s model=%s",
            embed_request.provider_type,
            embed_request.model_name,
        )
        raise HTTPException(
            status_code=500, detail=f"Error during embedding process: {e}"
        )
