import math
from collections.abc import Sequence

from onyx.natural_language_processing.embedding_providers.gemini import (
    gemini_base_model_name,
    is_gemini_embedding_2_model,
)
from shared_configs.configs import VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE

_MAX_TEXTS_PER_REQUEST = 250
# text-embedding-* and text-multilingual-embedding-* refuse larger requests.
_TEXT_EMBEDDING_MAX_TOKENS_PER_REQUEST = 20_000
# auto_truncate cuts each text to this length.
_MAX_TOKENS_PER_TEXT = 2048
# An overestimate for prose and tables. A token limit error splits the batch
# when the text is denser, such as CJK.
_CHARS_PER_TOKEN_ESTIMATE = 2.5


def vertex_batches(texts: Sequence[str], model: str) -> list[list[str]]:
    if is_gemini_embedding_2_model(model):
        return [[text] for text in texts]

    # The scheduler bounds requests in flight, so this bounds their memory.
    max_texts = min(_MAX_TEXTS_PER_REQUEST, VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE)
    max_tokens = (
        None if _is_gemini_model(model) else _TEXT_EMBEDDING_MAX_TOKENS_PER_REQUEST
    )
    batches: list[list[str]] = []
    batch: list[str] = []
    batch_tokens = 0
    for text in texts:
        tokens = _estimated_tokens(text)
        full = len(batch) == max_texts or (
            max_tokens is not None and batch_tokens + tokens > max_tokens
        )
        if batch and full:
            batches.append(batch)
            batch, batch_tokens = [], 0
        batch.append(text)
        batch_tokens += tokens
    if batch:
        batches.append(batch)
    return batches


def is_token_limit_error(error: BaseException) -> bool:
    from google.genai import errors as genai_errors

    return (
        isinstance(error, genai_errors.ClientError)
        and error.code == 400
        and "input token count" in (error.message or "")
    )


def _is_gemini_model(model: str) -> bool:
    return gemini_base_model_name(model).startswith("gemini-embedding")


def _estimated_tokens(text: str) -> int:
    return min(math.ceil(len(text) / _CHARS_PER_TOKEN_ESTIMATE), _MAX_TOKENS_PER_TEXT)
