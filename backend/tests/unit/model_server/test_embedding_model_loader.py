from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch
from safetensors.torch import save_file
from sentence_transformers.base.modules import Transformer
from sentence_transformers.sentence_transformer.modules import Dense

from model_server import embedding_model_loader as loader
from model_server.embedding_model_loader import (
    EmbeddingModelLoadError,
    load_embedding_model,
)
from model_server.voyage_nano import VOYAGE_NANO_PROJECTION_FILE
from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from shared_configs.embedding_models import EmbeddingModelSpec, get_local_model_spec

_ST_CLASS = "sentence_transformers.SentenceTransformer"
_MODULES_JSON_IS_CACHED = "model_server.embedding_model_loader._modules_json_is_cached"
_HF_HUB_DOWNLOAD = "huggingface_hub.hf_hub_download"
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _registry_spec(model_name: str) -> EmbeddingModelSpec:
    spec = get_local_model_spec(model_name)
    assert spec is not None
    return spec


_GRANITE = _registry_spec(DEFAULT_DOCUMENT_ENCODER_MODEL)
_VOYAGE = _registry_spec("voyageai/voyage-4-nano")


def _fake_model(dim: int) -> MagicMock:
    model = MagicMock()
    model.encode.return_value = np.zeros((1, dim), dtype=np.float32)
    return model


# ---- Registry models ----


@pytest.mark.parametrize(
    ("cuda", "mps", "model_kwargs"),
    [
        (False, False, {"dtype": torch.float32}),
        (True, False, {}),
        (False, True, {}),
    ],
    ids=["cpu", "cuda", "mps"],
)
def test_registry_model_load_call(
    cuda: bool,
    mps: bool,
    model_kwargs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pinned revision, no remote code, the local cache first. CPU-only hosts
    load the bf16 checkpoints as float32."""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: cuda)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: mps)
    model = _fake_model(_GRANITE.model_dim)
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True) as is_cached,
        patch(_ST_CLASS, return_value=model) as load,
    ):
        assert load_embedding_model(_GRANITE.model_name) is model

    is_cached.assert_called_once_with(_GRANITE.model_name, _GRANITE.hf_revision)
    load.assert_called_once_with(
        model_name_or_path=_GRANITE.model_name,
        revision=_GRANITE.hf_revision,
        trust_remote_code=False,
        local_files_only=True,
        model_kwargs=model_kwargs,
    )


@pytest.mark.parametrize(
    ("output", "error"),
    [
        (np.zeros((1, _GRANITE.model_dim // 2)), f"expects {_GRANITE.model_dim}"),
        (np.full((1, _GRANITE.model_dim), np.nan), "non-finite"),
    ],
    ids=["wrong-dim", "non-finite"],
)
def test_registry_model_with_unusable_output_is_rejected(
    output: np.ndarray, error: str
) -> None:
    model = MagicMock()
    model.encode.return_value = output
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, return_value=model),
        pytest.raises(EmbeddingModelLoadError, match=error),
    ):
        load_embedding_model(_GRANITE.model_name)


@pytest.mark.parametrize(
    ("model_name", "cached"),
    [
        ("nomic-ai/nomic-embed-text-v1", True),
        ("my-org/custom-model", False),
        # Only the exact registry name gets the registry load.
        ("IBM-Granite/granite-embedding-97m-multilingual-r2", False),
    ],
)
def test_other_models_keep_the_load_call_from_before_the_registry(
    model_name: str, cached: bool
) -> None:
    """Another call would change the vectors of existing indexes."""
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=cached),
        patch(_ST_CLASS, return_value=MagicMock()) as load,
    ):
        load_embedding_model(model_name)

    load.assert_called_once_with(
        model_name_or_path=model_name,
        local_files_only=cached,
        trust_remote_code=False,
    )


def test_voyage_loader_adds_bidirectional_projection(tmp_path: Path) -> None:
    weight = torch.randn(6, 4)
    weights_path = tmp_path / VOYAGE_NANO_PROJECTION_FILE
    save_file({"linear.weight": weight, "other.weight": torch.zeros(1)}, weights_path)
    transformer = MagicMock(spec=Transformer)
    pooling = MagicMock()
    normalize = MagicMock()
    base = MagicMock()
    base.__getitem__.side_effect = [transformer, pooling, normalize].__getitem__
    final = _fake_model(_VOYAGE.model_dim)

    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, side_effect=[base, final]) as st_class,
        patch(_HF_HUB_DOWNLOAD, return_value=str(weights_path)) as download,
    ):
        assert load_embedding_model(_VOYAGE.model_name) is final

    base_load, rebuild = st_class.call_args_list
    assert base_load.kwargs["revision"] == _VOYAGE.hf_revision
    download.assert_called_once_with(
        _VOYAGE.model_name,
        VOYAGE_NANO_PROJECTION_FILE,
        revision=_VOYAGE.hf_revision,
        cache_dir=None,
    )

    assert transformer.auto_model.config.is_causal is False
    modules = rebuild.kwargs["modules"]
    assert modules[0] is transformer
    assert modules[1] is pooling
    assert modules[3] is normalize
    projection = modules[2]
    assert isinstance(projection, Dense)
    assert (projection.in_features, projection.out_features) == (4, 6)
    assert projection.linear.bias is None
    assert isinstance(projection.activation_function, torch.nn.Identity)
    assert torch.equal(projection.linear.weight.detach(), weight)
    # The dimension check ran on the final model.
    final.encode.assert_called_once()


# ---- Local-first resolution ----


@pytest.mark.parametrize(
    "error",
    [
        OSError("couldn't find them in the cached files"),
        ValueError("Unrecognized processing class"),
        TypeError("missing 1 required positional argument"),
    ],
)
def test_load_local_first_retries_online_on_partial_cache(error: Exception) -> None:
    calls: list[bool] = []

    def load(local_files_only: bool) -> str:
        calls.append(local_files_only)
        if local_files_only:
            raise error
        return "online"

    with patch(_MODULES_JSON_IS_CACHED, return_value=True):
        assert loader._load_local_first("org/model", None, load) == "online"
    assert calls == [True, False]


def test_load_local_first_raises_real_errors() -> None:
    calls: list[bool] = []

    def load(local_files_only: bool) -> str:
        calls.append(local_files_only)
        raise RuntimeError("Error(s) in loading state_dict")

    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        pytest.raises(RuntimeError, match="state_dict"),
    ):
        loader._load_local_first("org/model", None, load)
    assert calls == [True]


@pytest.mark.parametrize(
    ("cached", "expected_error"),
    [
        # The online retry reads the same cached files, so its error is the real one.
        (True, RuntimeError),
        # Air-gapped hosts get a clear error, not huggingface_hub's retry noise.
        (False, EmbeddingModelLoadError),
    ],
)
def test_load_local_first_online_failure(
    cached: bool, expected_error: type[Exception]
) -> None:
    def load(local_files_only: bool) -> str:
        if local_files_only:
            raise OSError("partial cache")
        raise RuntimeError("Cannot send a request, as the client has been closed.")

    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=cached),
        pytest.raises(RuntimeError) as exc_info,
    ):
        loader._load_local_first("org/model", None, load)

    # EmbeddingModelLoadError is a RuntimeError, so compare the exact type.
    assert type(exc_info.value) is expected_error
    if not cached:
        assert "org/model is not in the model server's Hugging Face cache" in str(
            exc_info.value
        )
        assert isinstance(exc_info.value.__cause__, RuntimeError)


def _make_hub_cache(
    root: Path,
    repo_id: str,
    commit: str,
    files: list[str],
    ref_main: bool,
    no_exist: list[str] | None = None,
) -> None:
    repo_dir = root / f"models--{repo_id.replace('/', '--')}"
    snapshot = repo_dir / "snapshots" / commit
    snapshot.mkdir(parents=True)
    for name in files:
        (snapshot / name).write_text("{}")
    if ref_main:
        (repo_dir / "refs").mkdir()
        (repo_dir / "refs" / "main").write_text(commit)
    for name in no_exist or []:
        marker = repo_dir / ".no_exist" / commit / name
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()


@pytest.fixture
def hub_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import huggingface_hub.constants

    cache = tmp_path / "hub"
    cache.mkdir()
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)
    monkeypatch.setattr(huggingface_hub.constants, "HF_HUB_CACHE", str(cache))
    return cache


def test_modules_json_is_cached(hub_cache: Path) -> None:
    _make_hub_cache(hub_cache, "org/st-model", _SHA_A, ["modules.json"], ref_main=True)
    # A snapshot at a pinned revision with no refs/main, like the image bake.
    _make_hub_cache(hub_cache, "org/pinned", _SHA_B, ["modules.json"], ref_main=False)
    # config.json and weights cached (e.g. by transformers) but no modules.json.
    _make_hub_cache(
        hub_cache,
        "org/partial",
        _SHA_A,
        ["config.json", "model.safetensors"],
        ref_main=True,
    )
    # A plain transformers model: the cache records that modules.json is absent.
    _make_hub_cache(
        hub_cache,
        "org/plain-hf",
        _SHA_A,
        ["config.json"],
        ref_main=True,
        no_exist=["modules.json"],
    )

    assert loader._modules_json_is_cached("org/st-model", None) is True
    assert loader._modules_json_is_cached("org/pinned", _SHA_B) is True
    assert loader._modules_json_is_cached("org/partial", None) is False
    assert loader._modules_json_is_cached("org/plain-hf", None) is True
    # A local directory is not a repo id. sentence-transformers reads it directly.
    assert loader._modules_json_is_cached("/models/my-model", None) is False
