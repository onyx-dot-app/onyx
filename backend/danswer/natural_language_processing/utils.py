import gc
import os
from collections.abc import Callable
from copy import copy
from typing import Any
from typing import Optional
from typing import TYPE_CHECKING

import tiktoken
from tiktoken.core import Encoding
from transformers import logging as transformer_logging  # type:ignore

from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.configs.model_configs import DOCUMENT_ENCODER_MODEL
from danswer.search.models import InferenceChunk
from danswer.utils.logger import setup_logger


if TYPE_CHECKING:
    from transformers import AutoTokenizer  # type: ignore


logger = setup_logger()
transformer_logging.set_verbosity_error()
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"


_TOKENIZER: tuple[Optional["AutoTokenizer"], str | None] = (None, None)
_LLM_TOKENIZER: Any = None
_LLM_TOKENIZER_ENCODE: Callable[[str], Any] | None = None


# NOTE: If no model_name is specified, it may not be using the "correct" tokenizer
# for cases where this is more important, be sure to refresh with the actual model name
# One case where it is not particularly important is in the document chunking flow,
# they're basically all using the sentencepiece tokenizer and whether it's cased or
# uncased does not really matter, they'll all generally end up with the same chunk lengths.
def get_default_tokenizer(model_name: str = DOCUMENT_ENCODER_MODEL) -> "AutoTokenizer":
    # NOTE: doing a local import here to avoid reduce memory usage caused by
    # processes importing this file despite not using any of this
    from transformers import AutoTokenizer  # type: ignore

    global _TOKENIZER
    if _TOKENIZER[0] is None or _TOKENIZER[1] != model_name:
        if _TOKENIZER[0] is not None:
            del _TOKENIZER
            gc.collect()

        _TOKENIZER = (AutoTokenizer.from_pretrained(model_name), model_name)

        if hasattr(_TOKENIZER[0], "is_fast") and _TOKENIZER[0].is_fast:
            os.environ["TOKENIZERS_PARALLELISM"] = "false"

    return _TOKENIZER[0]


def get_default_llm_tokenizer() -> Encoding:
    """Currently only supports the OpenAI default tokenizer: tiktoken"""
    global _LLM_TOKENIZER
    if _LLM_TOKENIZER is None:
        _LLM_TOKENIZER = tiktoken.get_encoding("cl100k_base")
    return _LLM_TOKENIZER


def get_default_llm_token_encode() -> Callable[[str], Any]:
    global _LLM_TOKENIZER_ENCODE
    if _LLM_TOKENIZER_ENCODE is None:
        tokenizer = get_default_llm_tokenizer()
        if isinstance(tokenizer, Encoding):
            return tokenizer.encode  # type: ignore

        # Currently only supports OpenAI encoder
        raise ValueError("Invalid Encoder selected")

    return _LLM_TOKENIZER_ENCODE


def tokenizer_trim_content(
    content: str, desired_length: int, tokenizer: Encoding
) -> str:
    tokens = tokenizer.encode(content)
    if len(tokens) > desired_length:
        content = tokenizer.decode(tokens[:desired_length])
    return content


def tokenizer_trim_chunks(
    chunks: list[InferenceChunk], max_chunk_toks: int = DOC_EMBEDDING_CONTEXT_SIZE
) -> list[InferenceChunk]:
    tokenizer = get_default_llm_tokenizer()
    new_chunks = copy(chunks)
    for ind, chunk in enumerate(new_chunks):
        new_content = tokenizer_trim_content(chunk.content, max_chunk_toks, tokenizer)
        if len(new_content) != len(chunk.content):
            new_chunk = copy(chunk)
            new_chunk.content = new_content
            new_chunks[ind] = new_chunk
    return new_chunks
