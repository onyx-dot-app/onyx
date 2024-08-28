import os
from abc import ABC
from abc import abstractmethod
from copy import copy

from transformers import logging as transformer_logging  # type:ignore

from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.configs.model_configs import DOCUMENT_ENCODER_MODEL
from danswer.search.models import InferenceChunk
from danswer.utils.logger import setup_logger
from shared_configs.enums import EmbeddingProvider

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
    _instances: dict[str, "TiktokenTokenizer"] = {}

    def __new__(cls, encoding_name: str = "cl100k_base") -> "TiktokenTokenizer":
        if encoding_name not in cls._instances:
            cls._instances[encoding_name] = super(TiktokenTokenizer, cls).__new__(cls)
        return cls._instances[encoding_name]

    def __init__(self, encoding_name: str = "cl100k_base"):
        if not hasattr(self, "encoder"):
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


def _check_tokenizer_cache(tokenizer_name: str) -> BaseTokenizer:
    global _TOKENIZER_CACHE

    if tokenizer_name not in _TOKENIZER_CACHE:
        if tokenizer_name == "openai":
            _TOKENIZER_CACHE[tokenizer_name] = TiktokenTokenizer("cl100k_base")
            return _TOKENIZER_CACHE[tokenizer_name]
        try:
            logger.debug(f"Initializing HuggingFaceTokenizer for: {tokenizer_name}")
            _TOKENIZER_CACHE[tokenizer_name] = HuggingFaceTokenizer(tokenizer_name)
        except Exception as primary_error:
            logger.error(
                f"Error initializing HuggingFaceTokenizer for {tokenizer_name}: {primary_error}"
            )
            logger.warning(
                f"Falling back to default embedding model: {DOCUMENT_ENCODER_MODEL}"
            )

            try:
                # Cache this tokenizer name to the default so we don't have to try to load it again
                # and fail again
                _TOKENIZER_CACHE[tokenizer_name] = HuggingFaceTokenizer(
                    DOCUMENT_ENCODER_MODEL
                )
            except Exception as fallback_error:
                logger.error(
                    f"Error initializing fallback HuggingFaceTokenizer: {fallback_error}"
                )
                raise ValueError(
                    f"Failed to initialize tokenizer for {tokenizer_name} and fallback model"
                ) from fallback_error

    return _TOKENIZER_CACHE[tokenizer_name]


_DEFAULT_TOKENIZER: BaseTokenizer = HuggingFaceTokenizer(DOCUMENT_ENCODER_MODEL)


def get_tokenizer(
    model_name: str | None, provider_type: EmbeddingProvider | str | None
) -> BaseTokenizer:
    # Currently all of the viable models use the same sentencepiece tokenizer
    # OpenAI uses a different one but currently it's not supported due to quality issues
    # the inconsistent chunking makes using the sentencepiece tokenizer default better for now
    # LLM tokenizers are specified by strings
    global _DEFAULT_TOKENIZER
    return _DEFAULT_TOKENIZER


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
