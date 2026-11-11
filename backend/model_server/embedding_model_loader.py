"""Loads self-hosted embedding models for the model server.

Registry models (the exact names that ``get_local_model_spec`` matches) load at
a pinned revision, in float32 on CPU-only hosts, with a per-model fix-up and an
output dimension check. Every other name (legacy and custom models) keeps the
``SentenceTransformer`` call from before the registry, so existing vectors do
not change; only the file lookup is local first. Settings come only from the
server-side registry, never from a request. All functions here block.
"""

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

import numpy as np
import torch

from model_server.voyage_nano import (
    VOYAGE_NANO_PROJECTION_FILE,
    add_bidirectional_projection,
    read_projection_weight,
)
from onyx.utils.logger import setup_logger
from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    LocalModelLoader,
    get_local_model_spec,
)

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = setup_logger()

_T = TypeVar("_T")

# What a local-only load raises when an interrupted download left a partial
# cache (sentence-transformers 5.4.1, huggingface-hub 1.26). The online retry
# downloads the missing files; a real load error comes back from that retry.
_PARTIAL_CACHE_ERRORS: tuple[type[Exception], ...] = (OSError, ValueError, TypeError)

# sentence-transformers reads this env var as its cache folder when it is set.
_SENTENCE_TRANSFORMERS_HOME_ENV = "SENTENCE_TRANSFORMERS_HOME"
_DIMENSION_PROBE_TEXT = "probe"


class EmbeddingModelLoadError(RuntimeError):
    """A self-hosted embedding model loaded, but is not usable."""


def _cache_dir() -> str | None:
    return os.environ.get(_SENTENCE_TRANSFORMERS_HOME_ENV) or None


def _modules_json_is_cached(model_name: str, revision: str | None) -> bool:
    """True if the cache has modules.json at this revision, or a marker that the
    repo has none. Without it, a local-only load silently builds default modules
    (mean pooling, no Normalize)."""
    from huggingface_hub import try_to_load_from_cache

    try:
        cached = try_to_load_from_cache(
            model_name, "modules.json", cache_dir=_cache_dir(), revision=revision
        )
    except ValueError:
        # Not a Hub repo id (e.g. a local directory). sentence-transformers
        # reads a local directory directly, with no download.
        return False
    return cached is not None


def _load_local_first(
    model_name: str,
    revision: str | None,
    load: Callable[[bool], _T],
) -> _T:
    """Run ``load(local_files_only)`` from the local cache first, then online, so
    a cached model (baked or downloaded before) loads with no network access."""
    cached = _modules_json_is_cached(model_name, revision)
    if cached:
        try:
            return load(True)
        except _PARTIAL_CACHE_ERRORS as e:
            logger.warning(
                "Could not load %s from the local cache (%s: %s). Loading it from Hugging Face.",
                model_name,
                type(e).__name__,
                e,
            )
    else:
        logger.notice(
            "%s is not in the model server's Hugging Face cache. Downloading it.",
            model_name,
        )
    try:
        return load(False)
    except Exception as e:
        if cached:
            raise
        # huggingface_hub reports an unreachable Hub with unclear errors (e.g.
        # "the client has been closed"). Say what is missing and what to do.
        raise EmbeddingModelLoadError(
            f"{model_name} is not in the model server's Hugging Face cache and "
            f"could not be downloaded ({type(e).__name__}: {e}). If this "
            "deployment has no internet access, add the model to the cache "
            f"({_cache_dir() or 'the default HF_HOME cache'}) first."
        ) from e


def _registry_model_kwargs() -> dict[str, Any]:
    """The new checkpoints are bf16, which is 8-10x slower than float32 on CPU,
    so CPU-only hosts load float32. CUDA and MPS keep the checkpoint dtype."""
    if torch.cuda.is_available() or torch.backends.mps.is_available():
        return {}
    return {"dtype": torch.float32}


def _check_embedding_dim(
    model: "SentenceTransformer", spec: EmbeddingModelSpec
) -> None:
    """Fail unless a probe embedding has the registry dimension and is finite. The
    configured dimension is not enough: a wrong voyage-4-nano load reports 2048
    but returns 1024-dim vectors."""
    probe = model.encode([_DIMENSION_PROBE_TEXT], show_progress_bar=False)
    dim = probe.shape[-1]
    if dim != spec.model_dim:
        raise EmbeddingModelLoadError(
            f"{spec.model_name} returned {dim}-dim vectors, but the registry "
            f"expects {spec.model_dim}. The model is not used."
        )
    if not np.isfinite(probe).all():
        raise EmbeddingModelLoadError(
            f"{spec.model_name} returned non-finite values for a probe text. "
            "The model is not used."
        )


def _load_registry_model(spec: EmbeddingModelSpec) -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer

    revision = spec.hf_revision
    model_kwargs = _registry_model_kwargs()

    def load(local_files_only: bool) -> "SentenceTransformer":
        return SentenceTransformer(
            model_name_or_path=spec.model_name,
            revision=revision,
            trust_remote_code=False,
            local_files_only=local_files_only,
            model_kwargs=model_kwargs,
        )

    model = _load_local_first(spec.model_name, revision, load)

    if spec.loader == LocalModelLoader.VOYAGE_BIDIRECTIONAL_PROJECTION:
        from huggingface_hub import hf_hub_download

        # The base load cached this file, and a commit-sha revision reads a
        # cached file with no network call.
        weights_path = hf_hub_download(
            spec.model_name,
            VOYAGE_NANO_PROJECTION_FILE,
            revision=revision,
            cache_dir=_cache_dir(),
        )
        model = add_bidirectional_projection(
            model, read_projection_weight(weights_path)
        )
        logger.info(
            "%s: transformers reports 'linear.weight' as UNEXPECTED. This is "
            "expected: Onyx adds it back as the projection layer.",
            spec.model_name,
        )

    _check_embedding_dim(model, spec)
    logger.notice(
        "Loaded %s at revision %s (device=%s, dtype=%s)",
        spec.model_name,
        revision,
        model.device,
        model.dtype,
    )
    return model


def _load_legacy_model(model_name: str) -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer

    def load(local_files_only: bool) -> "SentenceTransformer":
        # The call from before the registry. Only local_files_only changes.
        return SentenceTransformer(
            model_name_or_path=model_name,
            local_files_only=local_files_only,
            trust_remote_code=False,
        )

    return _load_local_first(model_name, None, load)


def load_embedding_model(model_name: str) -> "SentenceTransformer":
    """Load a self-hosted embedding model. Blocking; raises on failure."""
    spec = get_local_model_spec(model_name)
    if spec is not None:
        return _load_registry_model(spec)
    return _load_legacy_model(model_name)
