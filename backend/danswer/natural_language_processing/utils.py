import os
from abc import ABC
from abc import abstractmethod
from copy import copy

from transformers import logging as transformer_logging  # type:ignore

from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.configs.model_configs import DOCUMENT_ENCODER_MODEL
from danswer.search.models import InferenceChunk
from danswer.utils.logger import setup_logger

logger = setup_logger()
transformer_logging.set_verbosity_error()
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"


class BaseTokenizer(ABC):
    @abstractmethod
    def encode(self, string: str) -> list[int]:
        pass

    @abstractmethod
    def tokenize(self, string: str) -> list[str]:
        pass

    @abstractmethod
    def decode(self, tokens: list[int]) -> str:
        pass


class TiktokenTokenizer(BaseTokenizer):
    def __init__(self, encoding_name: str = "cl100k_base"):
        import tiktoken

        self.encoder = tiktoken.get_encoding(encoding_name)

    def encode(self, string: str) -> list[int]:
        # this returns no special tokens
        return self.encoder.encode_ordinary(string)

    def tokenize(self, string: str) -> list[str]:
        return [self.encoder.decode([token]) for token in self.encode(string)]

    def decode(self, tokens: list[int]) -> str:
        return self.encoder.decode(tokens)


class HuggingFaceTokenizer(BaseTokenizer):
    def __init__(self, model_name: str):
        from tokenizers import Tokenizer  # type: ignore

        self.encoder = Tokenizer.from_pretrained(model_name)

    def encode(self, string: str) -> list[int]:
        # this returns no special tokens
        return self.encoder.encode(string, add_special_tokens=False).ids

    def tokenize(self, string: str) -> list[str]:
        return self.encoder.encode(string, add_special_tokens=False).tokens

    def decode(self, tokens: list[int]) -> str:
        return self.encoder.decode(tokens)


_TOKENIZER_CACHE: dict[str, BaseTokenizer] = {}


def _get_cached_tokenizer(
    model_name: str | None = None, provider_type: str | None = None
) -> BaseTokenizer:
    global _TOKENIZER_CACHE

    if provider_type:
        if not _TOKENIZER_CACHE.get(provider_type):
            if provider_type.lower() == "openai":
                _TOKENIZER_CACHE[provider_type] = TiktokenTokenizer()
            elif provider_type.lower() == "cohere":
                _TOKENIZER_CACHE[provider_type] = HuggingFaceTokenizer(
                    "Cohere/command-nightly"
                )
            else:
                _TOKENIZER_CACHE[
                    provider_type
                ] = TiktokenTokenizer()  # Default to OpenAI tokenizer
        return _TOKENIZER_CACHE[provider_type]

    if model_name:
        if not _TOKENIZER_CACHE.get(model_name):
            _TOKENIZER_CACHE[model_name] = HuggingFaceTokenizer(model_name)
        return _TOKENIZER_CACHE[model_name]

    raise ValueError("Need to provide a model_name or provider_type")


def get_tokenizer(model_name: str | None, provider_type: str | None) -> BaseTokenizer:
    if provider_type is None and model_name is None:
        model_name = DOCUMENT_ENCODER_MODEL
    return _get_cached_tokenizer(
        model_name=model_name,
        provider_type=provider_type,
    )


def tokenizer_trim_content(
    content: str, desired_length: int, tokenizer: BaseTokenizer
) -> str:
    tokens = tokenizer.encode(content)
    if len(tokens) > desired_length:
        content = tokenizer.decode(tokens[:desired_length])
    return content


def tokenizer_trim_chunks(
    chunks: list[InferenceChunk],
    tokenizer: BaseTokenizer,
    max_chunk_toks: int = DOC_EMBEDDING_CONTEXT_SIZE,
) -> list[InferenceChunk]:
    new_chunks = copy(chunks)
    for ind, chunk in enumerate(new_chunks):
        new_content = tokenizer_trim_content(chunk.content, max_chunk_toks, tokenizer)
        if len(new_content) != len(chunk.content):
            new_chunk = copy(chunk)
            new_chunk.content = new_content
            new_chunks[ind] = new_chunk
    return new_chunks
