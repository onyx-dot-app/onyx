"""Registry of known embedding models, shared by the API server (upgrade-only
guard, tokenizer revision, config defaults) and the model server (loader
settings). Keep it pure (pydantic, the stdlib, ``shared_configs``): the
model-server image has no ``onyx`` package and the API image has no torch.

Only add entries: a deployment can hold any entry as PRESENT, FUTURE or PAST.
``model_name`` is the exact ``SearchSettings.model_name``: the bare name for
cloud providers, the HF repo id for self-hosted models.
"""

from enum import Enum

from pydantic import BaseModel

from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from shared_configs.enums import EmbeddingProvider
from shared_configs.utils import clean_model_name


class EmbeddingModelStatus(str, Enum):
    """Whether a model can be chosen as a new embedding target."""

    # Offered to admins as a new target.
    SELECTABLE = "selectable"
    # Kept only so existing deployments keep working. Not a valid new target,
    # except for a same-model re-index of the PRESENT model.
    LEGACY = "legacy"


class LocalModelLoader(str, Enum):
    """How the model server loads a SELECTABLE self-hosted model."""

    # Plain SentenceTransformer load.
    STANDARD = "standard"
    # voyage-4-nano: native Qwen3 with bidirectional attention, plus the
    # bias-free 1024 -> 2048 projection from the checkpoint. No remote code.
    VOYAGE_BIDIRECTIONAL_PROJECTION = "voyage_bidirectional_projection"


class EmbeddingModelSpec(BaseModel, frozen=True):
    """One known embedding model. LEGACY values only seed env defaults
    (``onyx.configs.model_configs``). Stored rows often differ (e.g. empty
    prefixes), so never compare a request or a row against them."""

    # None means self-hosted (the model server runs it).
    provider_type: EmbeddingProvider | None
    model_name: str
    model_dim: int
    normalize: bool
    query_prefix: str
    passage_prefix: str
    status: EmbeddingModelStatus
    # Pinned HF commit sha. Set only for SELECTABLE self-hosted models.
    hf_revision: str | None = None
    loader: LocalModelLoader = LocalModelLoader.STANDARD
    # True if the embedding path honors `reduced_dimension` (Matryoshka).
    supports_reduced_dimension: bool = False


_SELECTABLE = EmbeddingModelStatus.SELECTABLE
_LEGACY = EmbeddingModelStatus.LEGACY

_E5_QUERY_PREFIX = "query: "
_E5_PASSAGE_PREFIX = "passage: "


def _cloud_spec(
    provider_type: EmbeddingProvider,
    model_name: str,
    model_dim: int,
    status: EmbeddingModelStatus,
    supports_reduced_dimension: bool = False,
) -> EmbeddingModelSpec:
    """Cloud models: no Onyx-side normalize and no prefixes."""
    return EmbeddingModelSpec(
        provider_type=provider_type,
        model_name=model_name,
        model_dim=model_dim,
        normalize=False,
        query_prefix="",
        passage_prefix="",
        status=status,
        supports_reduced_dimension=supports_reduced_dimension,
    )


def _legacy_self_hosted_spec(
    model_name: str,
    model_dim: int,
    normalize: bool,
    query_prefix: str,
    passage_prefix: str,
) -> EmbeddingModelSpec:
    return EmbeddingModelSpec(
        provider_type=None,
        model_name=model_name,
        model_dim=model_dim,
        normalize=normalize,
        query_prefix=query_prefix,
        passage_prefix=passage_prefix,
        status=_LEGACY,
    )


EMBEDDING_MODEL_SPECS: tuple[EmbeddingModelSpec, ...] = (
    # ---- SELECTABLE: self-hosted ----
    EmbeddingModelSpec(
        provider_type=None,
        model_name=DEFAULT_DOCUMENT_ENCODER_MODEL,
        model_dim=384,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        status=_SELECTABLE,
        hf_revision="835ad14087e140460703cf0fae09f97d469d65c2",
    ),
    EmbeddingModelSpec(
        provider_type=None,
        model_name="voyageai/voyage-4-nano",
        model_dim=2048,
        normalize=True,
        query_prefix="Represent the query for retrieving supporting documents: ",
        passage_prefix="Represent the document for retrieval: ",
        status=_SELECTABLE,
        hf_revision="67fabc9bef010dabc5f6024aa1b1b6b93410426f",
        loader=LocalModelLoader.VOYAGE_BIDIRECTIONAL_PROJECTION,
    ),
    EmbeddingModelSpec(
        provider_type=None,
        model_name="nvidia/Nemotron-3-Embed-1B-BF16",
        model_dim=2048,
        normalize=True,
        query_prefix="query: ",
        passage_prefix="passage: ",
        status=_SELECTABLE,
        hf_revision="c0c9fea93ea424587517f2c59e20db9f1d6bf615",
    ),
    # ---- SELECTABLE: cloud ----
    _cloud_spec(EmbeddingProvider.COHERE, "embed-v5.0-pro", 2048, _SELECTABLE),
    _cloud_spec(EmbeddingProvider.COHERE, "embed-v5.0-fast", 2048, _SELECTABLE),
    _cloud_spec(
        EmbeddingProvider.GOOGLE,
        "gemini-embedding-2",
        3072,
        _SELECTABLE,
        supports_reduced_dimension=True,
    ),
    _cloud_spec(
        EmbeddingProvider.OPENAI,
        "text-embedding-3-large",
        3072,
        _SELECTABLE,
        supports_reduced_dimension=True,
    ),
    _cloud_spec(
        EmbeddingProvider.OPENAI,
        "text-embedding-3-small",
        1536,
        _SELECTABLE,
        supports_reduced_dimension=True,
    ),
    _cloud_spec(EmbeddingProvider.VOYAGE, "voyage-4-large", 1024, _SELECTABLE),
    _cloud_spec(EmbeddingProvider.VOYAGE, "voyage-4", 1024, _SELECTABLE),
    _cloud_spec(EmbeddingProvider.VOYAGE, "voyage-4-lite", 1024, _SELECTABLE),
    # ---- LEGACY: self-hosted ----
    _legacy_self_hosted_spec(
        "nomic-ai/nomic-embed-text-v1", 768, True, "search_query: ", "search_document: "
    ),
    _legacy_self_hosted_spec(
        "intfloat/e5-base-v2", 768, True, _E5_QUERY_PREFIX, _E5_PASSAGE_PREFIX
    ),
    _legacy_self_hosted_spec(
        "intfloat/e5-small-v2", 384, True, _E5_QUERY_PREFIX, _E5_PASSAGE_PREFIX
    ),
    _legacy_self_hosted_spec(
        "intfloat/multilingual-e5-base", 768, True, _E5_QUERY_PREFIX, _E5_PASSAGE_PREFIX
    ),
    _legacy_self_hosted_spec(
        "intfloat/multilingual-e5-small",
        384,
        True,
        _E5_QUERY_PREFIX,
        _E5_PASSAGE_PREFIX,
    ),
    _legacy_self_hosted_spec("thenlper/gte-small", 384, False, "", ""),
    # ---- LEGACY: cloud ----
    _cloud_spec(EmbeddingProvider.COHERE, "embed-english-v3.0", 1024, _LEGACY),
    _cloud_spec(EmbeddingProvider.COHERE, "embed-english-light-v3.0", 384, _LEGACY),
    _cloud_spec(EmbeddingProvider.COHERE, "embed-v4.0", 1536, _LEGACY),
    _cloud_spec(EmbeddingProvider.GOOGLE, "gemini-embedding-001", 3072, _LEGACY),
    _cloud_spec(EmbeddingProvider.GOOGLE, "text-embedding-005", 768, _LEGACY),
    _cloud_spec(EmbeddingProvider.GOOGLE, "gemini-embedding-2-preview", 3072, _LEGACY),
    _cloud_spec(EmbeddingProvider.GOOGLE, "text-embedding-004", 768, _LEGACY),
    _cloud_spec(EmbeddingProvider.GOOGLE, "textembedding-gecko@003", 768, _LEGACY),
    _cloud_spec(EmbeddingProvider.VOYAGE, "voyage-large-2-instruct", 1024, _LEGACY),
    _cloud_spec(EmbeddingProvider.VOYAGE, "voyage-light-2-instruct", 1024, _LEGACY),
)


def embedding_model_match_key(
    provider_type: EmbeddingProvider | None, model_name: str
) -> tuple[EmbeddingProvider | None, str]:
    """The fold that names indexes, so case, punctuation and whitespace variants
    of a model name match."""
    return provider_type, clean_model_name(model_name.strip())


_SPECS_BY_MATCH_KEY = {
    embedding_model_match_key(spec.provider_type, spec.model_name): spec
    for spec in EMBEDDING_MODEL_SPECS
}
if len(_SPECS_BY_MATCH_KEY) != len(EMBEDDING_MODEL_SPECS):
    raise ValueError("Two embedding model specs share a match key")


def find_embedding_model_spec(
    provider_type: EmbeddingProvider | None, model_name: str
) -> EmbeddingModelSpec | None:
    """The SELECTABLE or LEGACY spec for ``embedding_model_match_key``, or None."""
    return _SPECS_BY_MATCH_KEY.get(embedding_model_match_key(provider_type, model_name))


def get_local_model_spec(model_name: str) -> EmbeddingModelSpec | None:
    """The spec the model server loads ``model_name`` with: only the exact name of
    a pinned SELECTABLE self-hosted entry. Any other name (legacy, custom, a case
    variant) returns None and keeps the legacy load."""
    for spec in EMBEDDING_MODEL_SPECS:
        if (
            spec.provider_type is None
            and spec.status == EmbeddingModelStatus.SELECTABLE
            and spec.hf_revision is not None
            and spec.model_name == model_name
        ):
            return spec
    return None


def selectable_embedding_model_specs() -> tuple[EmbeddingModelSpec, ...]:
    """Return the SELECTABLE entries, in registry order."""
    return tuple(
        spec
        for spec in EMBEDDING_MODEL_SPECS
        if spec.status == EmbeddingModelStatus.SELECTABLE
    )
