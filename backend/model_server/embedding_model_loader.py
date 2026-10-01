"""Loads self-hosted embedding models for the model server.

There are two load paths:

- Registry models: SELECTABLE self-hosted entries of
  ``shared_configs.embedding_models`` (see ``get_local_model_spec``). They load
  at a pinned revision, in float32 on CPU-only hosts, with a per-model fix-up
  if the spec asks for one, and a check of the output dimension.
- Every other name (legacy models such as nomic and e5, and custom Hugging Face
  ids): the same ``SentenceTransformer`` call as before the registry existed.
  Only the file resolution changed (local first, see ``_load_local_first``).
  Changing this call changes the vectors of existing indexes.

Loader settings come only from the server-side registry, keyed by the exact
model name. A request never carries a revision, a dtype or trust_remote_code.
It can carry the dimension stored for the model, which only decides whether a
registry name is really the registry model (see ``resolve_local_model_spec``).
All functions here block (file IO, downloads). Do not call them on the event
loop.
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

# Errors from a load with local_files_only=True when the cache holds only part
# of the model, checked on sentence-transformers 5.4.1 and huggingface-hub 1.26:
# - OSError: a missing config.json (caused by huggingface_hub's
#   LocalEntryNotFoundError, which is also an OSError) or missing weights.
# - ValueError: missing tokenizer files, or missing Dense weights.
# - TypeError: a missing module config, e.g. 1_Pooling/config.json.
# A partial cache comes from an interrupted download (for example, the process
# was killed while it loaded the weights). The online retry downloads the
# missing files. A real load error comes back from the online retry, which
# reads the same cached files, so it is not hidden.
_PARTIAL_CACHE_ERRORS: tuple[type[Exception], ...] = (OSError, ValueError, TypeError)

# sentence-transformers reads this env var as its cache folder when it is set.
_SENTENCE_TRANSFORMERS_HOME_ENV = "SENTENCE_TRANSFORMERS_HOME"
_DIMENSION_PROBE_TEXT = "probe"


class EmbeddingModelLoadError(RuntimeError):
    """A self-hosted embedding model loaded, but is not usable."""


def _cache_dir() -> str | None:
    return os.environ.get(_SENTENCE_TRANSFORMERS_HOME_ENV) or None


def _modules_json_is_cached(model_name: str, revision: str | None) -> bool:
    """True if the local cache knows about modules.json at this revision.

    The cache either has the file, or has a marker that the repo has no
    modules.json (a plain transformers model). Without this check, a cache
    with config.json and weights but no modules.json makes a local-only load
    build default modules (mean pooling, no Normalize) without an error.
    """
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
    """Run ``load(local_files_only)`` from the local cache first, then online.

    A cached model (baked into the image, or downloaded before) loads with no
    network access, which air-gapped deployments need. A model that is not
    cached downloads as usual.
    """
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


def _hf_hub_download_local_first(repo_id: str, filename: str, revision: str) -> str:
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return hf_hub_download(
            repo_id,
            filename,
            revision=revision,
            cache_dir=_cache_dir(),
            local_files_only=True,
        )
    except LocalEntryNotFoundError:
        return hf_hub_download(
            repo_id, filename, revision=revision, cache_dir=_cache_dir()
        )


def _registry_model_kwargs() -> dict[str, Any]:
    """transformers' model kwargs for registry models on this host.

    The new checkpoints are bf16, and transformers loads them as bf16 by
    default. bf16 on CPU is about 8-10x slower than float32, so CPU-only hosts
    use float32. CUDA and MPS keep the checkpoint dtype.
    """
    if torch.cuda.is_available() or torch.backends.mps.is_available():
        return {}
    return {"dtype": torch.float32}


def _check_embedding_dim(
    model: "SentenceTransformer", spec: EmbeddingModelSpec
) -> None:
    """Fail if the model's vectors do not match the registry dimension.

    The configured dimension is not enough: a wrong voyage-4-nano load reports
    2048 but returns 1024-dim vectors.
    """
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
    if revision is None:
        raise EmbeddingModelLoadError(
            f"{spec.model_name} has no pinned revision in the registry."
        )
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
        weights_path = _hf_hub_download_local_first(
            spec.model_name, VOYAGE_NANO_PROJECTION_FILE, revision
        )
        model = add_bidirectional_projection(
            model, read_projection_weight(weights_path)
        )
        logger.info(
            "%s: transformers reports 'linear.weight' as UNEXPECTED. This is "
            "expected: Onyx adds it back as the projection layer.",
            spec.model_name,
        )
    elif spec.loader != LocalModelLoader.STANDARD:
        raise EmbeddingModelLoadError(
            f"{spec.model_name} uses an unknown loader: {spec.loader}."
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


def resolve_local_model_spec(
    model_name: str, expected_dim: int | None
) -> EmbeddingModelSpec | None:
    """The registry spec that loads ``model_name``, or None for the legacy load.

    A registry model matches on its exact name (``get_local_model_spec``), with
    one exception. Before the registry existed, an admin could add a model with
    the same name through "Add Custom Model". That row's index holds vectors
    from the legacy load. For voyage-4-nano these are 1024-dim causal vectors,
    and the registry load returns 2048-dim vectors that the index rejects. The
    API sends the dimension stored for the model as ``expected_dim``. If it
    differs from the registry dimension, the row is such a custom model and
    keeps the legacy load. ``expected_dim`` None (an older API server) keeps the
    registry load.
    """
    spec = get_local_model_spec(model_name)
    if spec is None or expected_dim is None or expected_dim == spec.model_dim:
        return spec
    return None


def is_registry_model(model_name: str, expected_dim: int | None = None) -> bool:
    return resolve_local_model_spec(model_name, expected_dim) is not None


def load_embedding_model(
    model_name: str, expected_dim: int | None = None
) -> "SentenceTransformer":
    """Load a self-hosted embedding model. Blocking; raises on failure."""
    spec = resolve_local_model_spec(model_name, expected_dim)
    if spec is not None:
        return _load_registry_model(spec)

    registry_spec = get_local_model_spec(model_name)
    if registry_spec is not None:
        logger.warning(
            "%s is stored with %s dimensions, but the Onyx model with this name "
            "has %s. Loading it as a custom model, as before the model registry, "
            "so that its index keeps working. To use the Onyx model, re-index to "
            "%s with %s dimensions.",
            model_name,
            expected_dim,
            registry_spec.model_dim,
            registry_spec.model_name,
            registry_spec.model_dim,
        )
    return _load_legacy_model(model_name)
