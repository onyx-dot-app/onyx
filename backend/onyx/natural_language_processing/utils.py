import os
from abc import ABC
from abc import abstractmethod
from copy import copy

from tokenizers import Encoding  # type: ignore
from tokenizers import Tokenizer  # type: ignore

from onyx.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from onyx.configs.model_configs import DOCUMENT_ENCODER_MODEL
from onyx.context.search.models import InferenceChunk
from onyx.utils.logger import setup_logger
from shared_configs.enums import EmbeddingProvider

TRIM_SEP_PAT = "\n... {n} tokens removed...\n"

logger = setup_logger()
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


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
        self.encoder: Tokenizer = Tokenizer.from_pretrained(model_name)

    def _safer_encode(self, string: str) -> Encoding:
        """
        Encode a string using the HuggingFaceTokenizer, but if it fails,
        encode the string as ASCII and decode it back to a string. This helps
        in cases where the string has weird characters like \udeb4.
        """
        try:
            return self.encoder.encode(string, add_special_tokens=False)
        except Exception:
            return self.encoder.encode(
                string.encode("ascii", "ignore").decode(), add_special_tokens=False
            )

    def encode(self, string: str) -> list[int]:
        # this returns no special tokens
        return self._safer_encode(string).ids

    def tokenize(self, string: str) -> list[str]:
        return self._safer_encode(string).tokens

    def decode(self, tokens: list[int]) -> str:
        return self.encoder.decode(tokens)


_TOKENIZER_CACHE: dict[tuple[EmbeddingProvider | None, str | None], BaseTokenizer] = {}


def _check_tokenizer_cache(
    model_provider: EmbeddingProvider | None, model_name: str | None
) -> BaseTokenizer:
    global _TOKENIZER_CACHE
    id_tuple = (model_provider, model_name)

    if id_tuple not in _TOKENIZER_CACHE:
        tokenizer = None

        if model_name:
            tokenizer = _try_initialize_tokenizer(model_name, model_provider)

        if not tokenizer:
            logger.info(
                f"Falling back to default embedding model tokenizer: {DOCUMENT_ENCODER_MODEL}"
            )
            tokenizer = _get_default_tokenizer()

        _TOKENIZER_CACHE[id_tuple] = tokenizer

    return _TOKENIZER_CACHE[id_tuple]


def _try_initialize_tokenizer(
    model_name: str, model_provider: EmbeddingProvider | None
) -> BaseTokenizer | None:
    tokenizer: BaseTokenizer | None = None

    if model_provider is not None:
        # Try using TiktokenTokenizer first if model_provider exists
        try:
            tokenizer = TiktokenTokenizer(model_name)
            logger.info(f"Initialized TiktokenTokenizer for: {model_name}")
            return tokenizer
        except Exception as tiktoken_error:
            logger.debug(
                f"TiktokenTokenizer not available for model {model_name}: {tiktoken_error}"
            )
    else:
        # If no provider specified, try HuggingFaceTokenizer
        try:
            tokenizer = HuggingFaceTokenizer(model_name)
            logger.info(f"Initialized HuggingFaceTokenizer for: {model_name}")
            return tokenizer
        except Exception as hf_error:
            logger.warning(
                f"Failed to initialize HuggingFaceTokenizer for {model_name}: {hf_error}"
            )

    # If both initializations fail, return None
    return None


_DEFAULT_TOKENIZER: BaseTokenizer | None = None


def _get_default_tokenizer() -> BaseTokenizer:
    """Lazy-load the default tokenizer to avoid loading it at module import time."""
    global _DEFAULT_TOKENIZER
    if _DEFAULT_TOKENIZER is None:
        _DEFAULT_TOKENIZER = HuggingFaceTokenizer(DOCUMENT_ENCODER_MODEL)
    return _DEFAULT_TOKENIZER


def get_tokenizer(
    model_name: str | None, provider_type: EmbeddingProvider | str | None
) -> BaseTokenizer:
    if isinstance(provider_type, str):
        try:
            provider_type = EmbeddingProvider(provider_type)
        except ValueError:
            logger.debug(
                f"Invalid provider_type '{provider_type}'. Falling back to default tokenizer."
            )
            return _get_default_tokenizer()
    return _check_tokenizer_cache(provider_type, model_name)


def tokenizer_trim_content(
    content: str, desired_length: int, tokenizer: BaseTokenizer
) -> str:
    tokens = tokenizer.encode(content)
    if len(tokens) <= desired_length:
        return content

    return tokenizer.decode(tokens[:desired_length])


def tokenizer_trim_middle(
    tokens: list[int], desired_length: int, tokenizer: BaseTokenizer
) -> str:
    if len(tokens) <= desired_length:
        return tokenizer.decode(tokens)
    sep_str = TRIM_SEP_PAT.format(n=len(tokens) - desired_length)
    sep_tokens = tokenizer.encode(sep_str)
    slice_size = (desired_length - len(sep_tokens)) // 2
    assert slice_size > 0, "Slice size is not positive, desired length is too short"
    return (
        tokenizer.decode(tokens[:slice_size])
        + sep_str
        + tokenizer.decode(tokens[-slice_size:])
    )


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
