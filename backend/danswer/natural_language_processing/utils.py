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

    def __new__(cls, model_name: str) -> "TiktokenTokenizer":
        if model_name not in cls._instances:
            cls._instances[model_name] = super(TiktokenTokenizer, cls).__new__(cls)
        return cls._instances[model_name]

    def __init__(self, model_name: str):
        if not hasattr(self, "encoder"):
            import tiktoken

            self.encoder = tiktoken.encoding_for_model(model_name)

    def encode(self, string: str) -> list[int]:
        # this ignores special tokens that the model is trained on, see encode_ordinary for details
        return self.encoder.encode_ordinary(string)

    def tokenize(self, string: str) -> list[str]:
        encoded = self.encode(string)
        decoded = [self.encoder.decode([token]) for token in encoded]

        if len(decoded) != len(encoded):
            logger.warning(
                f"OpenAI tokenized length {len(decoded)} does not match encoded length {len(encoded)} for string: {string}"
            )

        return decoded

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


_TOKENIZER_CACHE: dict[tuple[EmbeddingProvider | None, str | None], BaseTokenizer] = {}


def _check_tokenizer_cache(
    model_provider: EmbeddingProvider | None, model_name: str | None
) -> BaseTokenizer:
    global _TOKENIZER_CACHE

    id_tuple = (model_provider, model_name)

    if id_tuple not in _TOKENIZER_CACHE:
        if model_provider in [EmbeddingProvider.OPENAI, EmbeddingProvider.AZURE]:
            if model_name is None:
                raise ValueError(
                    "model_name is required for OPENAI and AZURE embeddings"
                )

            _TOKENIZER_CACHE[id_tuple] = TiktokenTokenizer(model_name)
            return _TOKENIZER_CACHE[id_tuple]

        try:
            if model_name is None:
                model_name = DOCUMENT_ENCODER_MODEL

            logger.debug(f"Initializing HuggingFaceTokenizer for: {model_name}")
            _TOKENIZER_CACHE[id_tuple] = HuggingFaceTokenizer(model_name)
        except Exception as primary_error:
            logger.error(
                f"Error initializing HuggingFaceTokenizer for {model_name}: {primary_error}"
            )
            logger.warning(
                f"Falling back to default embedding model: {DOCUMENT_ENCODER_MODEL}"
            )

            try:
                # Cache this tokenizer name to the default so we don't have to try to load it again
                # and fail again
                _TOKENIZER_CACHE[id_tuple] = HuggingFaceTokenizer(
                    DOCUMENT_ENCODER_MODEL
                )
            except Exception as fallback_error:
                logger.error(
                    f"Error initializing fallback HuggingFaceTokenizer: {fallback_error}"
                )
                raise ValueError(
                    f"Failed to initialize tokenizer for {model_name} and fallback model"
                ) from fallback_error

    return _TOKENIZER_CACHE[id_tuple]


_DEFAULT_TOKENIZER: BaseTokenizer = HuggingFaceTokenizer(DOCUMENT_ENCODER_MODEL)


def get_tokenizer(
    model_name: str | None, provider_type: EmbeddingProvider | str | None
) -> BaseTokenizer:
    if provider_type is not None:
        if isinstance(provider_type, str):
            try:
                provider_type = EmbeddingProvider(provider_type)
            except ValueError:
                logger.debug(
                    f"Invalid provider_type '{provider_type}'. Falling back to default tokenizer."
                )
                return _DEFAULT_TOKENIZER
        return _check_tokenizer_cache(provider_type, model_name)
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
