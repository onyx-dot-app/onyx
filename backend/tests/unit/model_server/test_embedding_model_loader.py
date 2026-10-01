from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch
from huggingface_hub.errors import LocalEntryNotFoundError
from safetensors.torch import save_file
from sentence_transformers.base.modules import Transformer
from sentence_transformers.sentence_transformer.modules import Dense

from model_server import embedding_model_loader as loader
from model_server.embedding_model_loader import (
    EmbeddingModelLoadError,
    load_embedding_model,
)
from model_server.voyage_nano import (
    VOYAGE_NANO_PROJECTION_FILE,
    VoyageNanoLoadError,
    add_bidirectional_projection,
    read_projection_weight,
)
from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    LocalModelLoader,
    get_local_model_spec,
    selectable_embedding_model_specs,
)

_ST_CLASS = "sentence_transformers.SentenceTransformer"
_MODULES_JSON_IS_CACHED = "model_server.embedding_model_loader._modules_json_is_cached"
_HF_DOWNLOAD_LOCAL_FIRST = (
    "model_server.embedding_model_loader._hf_hub_download_local_first"
)
_SHA_A = "a" * 40
_SHA_B = "b" * 40

_REGISTRY_SPECS = [
    spec for spec in selectable_embedding_model_specs() if spec.provider_type is None
]
_VOYAGE_SPEC = next(
    spec
    for spec in _REGISTRY_SPECS
    if spec.loader == LocalModelLoader.VOYAGE_BIDIRECTIONAL_PROJECTION
)
_STANDARD_SPECS = [
    spec for spec in _REGISTRY_SPECS if spec.loader == LocalModelLoader.STANDARD
]


def _fake_model(dim: int) -> MagicMock:
    model = MagicMock()
    model.encode.return_value = np.zeros((1, dim), dtype=np.float32)
    return model


def _hide_accelerators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)


# ---- Registry models ----


def test_registry_covers_the_three_new_self_hosted_models() -> None:
    assert {spec.model_name for spec in _REGISTRY_SPECS} == {
        "ibm-granite/granite-embedding-97m-multilingual-r2",
        "voyageai/voyage-4-nano",
        "nvidia/Nemotron-3-Embed-1B-BF16",
    }
    for spec in _REGISTRY_SPECS:
        assert get_local_model_spec(spec.model_name) is spec


@pytest.mark.parametrize("spec", _STANDARD_SPECS, ids=lambda s: s.model_name)
def test_registry_model_load_call(
    spec: EmbeddingModelSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hide_accelerators(monkeypatch)
    model = _fake_model(spec.model_dim)
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True) as is_cached,
        patch(_ST_CLASS, return_value=model) as load,
    ):
        assert load_embedding_model(spec.model_name) is model

    is_cached.assert_called_once_with(spec.model_name, spec.hf_revision)
    load.assert_called_once_with(
        model_name_or_path=spec.model_name,
        revision=spec.hf_revision,
        trust_remote_code=False,
        local_files_only=True,
        model_kwargs={"dtype": torch.float32},
    )


@pytest.mark.parametrize(
    ("cuda", "mps", "expected"),
    [
        (False, False, {"dtype": torch.float32}),
        (True, False, {}),
        (False, True, {}),
    ],
)
def test_registry_model_dtype_policy(
    cuda: bool,
    mps: bool,
    expected: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: cuda)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: mps)
    spec = _STANDARD_SPECS[0]
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=False),
        patch(_ST_CLASS, return_value=_fake_model(spec.model_dim)) as load,
    ):
        load_embedding_model(spec.model_name)

    assert load.call_args.kwargs["model_kwargs"] == expected
    assert load.call_args.kwargs["local_files_only"] is False


def test_registry_model_partial_cache_retries_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hide_accelerators(monkeypatch)
    spec = _STANDARD_SPECS[0]
    model = _fake_model(spec.model_dim)
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, side_effect=[OSError("not cached"), model]) as load,
    ):
        assert load_embedding_model(spec.model_name) is model

    assert [c.kwargs["local_files_only"] for c in load.call_args_list] == [True, False]
    for call in load.call_args_list:
        assert call.kwargs["revision"] == spec.hf_revision
        assert call.kwargs["trust_remote_code"] is False


def test_registry_model_wrong_dimension_is_rejected() -> None:
    spec = _STANDARD_SPECS[0]
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, return_value=_fake_model(spec.model_dim // 2)),
        pytest.raises(EmbeddingModelLoadError, match=f"expects {spec.model_dim}"),
    ):
        load_embedding_model(spec.model_name)


def test_registry_model_non_finite_output_is_rejected() -> None:
    spec = _STANDARD_SPECS[0]
    model = MagicMock()
    model.encode.return_value = np.full((1, spec.model_dim), np.nan)
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, return_value=model),
        pytest.raises(EmbeddingModelLoadError, match="non-finite"),
    ):
        load_embedding_model(spec.model_name)


@pytest.mark.parametrize(
    "model_name",
    [
        "IBM-Granite/granite-embedding-97m-multilingual-r2",
        " voyageai/voyage-4-nano",
        "nvidia/nemotron-3-embed-1b-bf16",
    ],
)
def test_registry_name_variants_use_the_legacy_call(model_name: str) -> None:
    """Only the exact registry name gets the pinned revision and fix-ups."""
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=False),
        patch(_ST_CLASS, return_value=_fake_model(8)) as load,
    ):
        load_embedding_model(model_name)

    load.assert_called_once_with(
        model_name_or_path=model_name,
        local_files_only=False,
        trust_remote_code=False,
    )


@pytest.mark.parametrize("spec", _REGISTRY_SPECS, ids=lambda s: s.model_name)
def test_registry_name_with_another_stored_dim_uses_the_legacy_call(
    spec: EmbeddingModelSpec,
) -> None:
    """A custom model added before the registry under a registry name keeps the
    legacy load, so its existing index keeps working (e.g. voyage-4-nano at
    1024 dims)."""
    other_dim = spec.model_dim // 2
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, return_value=_fake_model(other_dim)) as load,
    ):
        load_embedding_model(spec.model_name, expected_dim=other_dim)

    load.assert_called_once_with(
        model_name_or_path=spec.model_name,
        local_files_only=True,
        trust_remote_code=False,
    )
    assert not loader.is_registry_model(spec.model_name, other_dim)


@pytest.mark.parametrize("expected_dim", [None, _VOYAGE_SPEC.model_dim])
def test_registry_name_with_registry_or_no_dim_resolves_to_the_registry(
    expected_dim: int | None,
) -> None:
    assert (
        loader.resolve_local_model_spec(_VOYAGE_SPEC.model_name, expected_dim)
        is _VOYAGE_SPEC
    )
    assert loader.is_registry_model(_VOYAGE_SPEC.model_name, expected_dim)


def test_stored_dim_never_makes_a_custom_name_a_registry_model() -> None:
    assert loader.resolve_local_model_spec("my-org/custom-model", 2048) is None


# ---- voyage-4-nano ----


def _write_projection(path: Path, weight: torch.Tensor) -> str:
    file_path = path / VOYAGE_NANO_PROJECTION_FILE
    save_file({"linear.weight": weight, "other.weight": torch.zeros(1)}, file_path)
    return str(file_path)


def _fake_voyage_base() -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    transformer = MagicMock(spec=Transformer)
    pooling = MagicMock()
    normalize = MagicMock()
    base = MagicMock()
    base.__len__.return_value = 3
    base.__getitem__.side_effect = [transformer, pooling, normalize].__getitem__
    return base, transformer, pooling, normalize


def test_voyage_loader_adds_bidirectional_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hide_accelerators(monkeypatch)
    weight = torch.randn(6, 4)
    weights_path = _write_projection(tmp_path, weight)
    base, transformer, pooling, normalize = _fake_voyage_base()
    final = _fake_model(_VOYAGE_SPEC.model_dim)

    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, side_effect=[base, final]) as st_class,
        patch(_HF_DOWNLOAD_LOCAL_FIRST, return_value=weights_path) as download,
    ):
        assert load_embedding_model(_VOYAGE_SPEC.model_name) is final

    base_load, rebuild = st_class.call_args_list
    assert base_load.kwargs == {
        "model_name_or_path": _VOYAGE_SPEC.model_name,
        "revision": _VOYAGE_SPEC.hf_revision,
        "trust_remote_code": False,
        "local_files_only": True,
        "model_kwargs": {"dtype": torch.float32},
    }
    download.assert_called_once_with(
        _VOYAGE_SPEC.model_name, VOYAGE_NANO_PROJECTION_FILE, _VOYAGE_SPEC.hf_revision
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
    # The final model passed the dimension check.
    final.encode.assert_called_once()


def test_voyage_loader_rejects_unexpected_module_layout() -> None:
    base = MagicMock()
    base.__len__.return_value = 2
    with pytest.raises(VoyageNanoLoadError, match="Expected 3 modules"):
        add_bidirectional_projection(base, torch.zeros(2, 2))

    base, _, _, _ = _fake_voyage_base()
    base.__getitem__.side_effect = [MagicMock(), MagicMock(), MagicMock()].__getitem__
    with pytest.raises(VoyageNanoLoadError, match="Transformer"):
        add_bidirectional_projection(base, torch.zeros(2, 2))


def test_read_projection_weight(tmp_path: Path) -> None:
    weight = torch.randn(3, 2)
    assert torch.equal(
        read_projection_weight(_write_projection(tmp_path, weight)), weight
    )

    missing = tmp_path / "missing.safetensors"
    save_file({"other.weight": torch.zeros(1)}, missing)
    with pytest.raises(VoyageNanoLoadError, match="linear.weight"):
        read_projection_weight(str(missing))


def test_voyage_projection_download_is_local_first() -> None:
    with patch("huggingface_hub.hf_hub_download", return_value="/cached") as download:
        assert (
            loader._hf_hub_download_local_first(
                "org/model", "model.safetensors", _SHA_A
            )
            == "/cached"
        )
    download.assert_called_once_with(
        "org/model",
        "model.safetensors",
        revision=_SHA_A,
        cache_dir=None,
        local_files_only=True,
    )

    with patch(
        "huggingface_hub.hf_hub_download",
        side_effect=[LocalEntryNotFoundError("not cached"), "/downloaded"],
    ) as download:
        assert (
            loader._hf_hub_download_local_first(
                "org/model", "model.safetensors", _SHA_A
            )
            == "/downloaded"
        )
    assert download.call_args_list[1].kwargs == {"revision": _SHA_A, "cache_dir": None}


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


def test_load_local_first_skips_cache_when_not_cached() -> None:
    calls: list[bool] = []

    def load(local_files_only: bool) -> str:
        calls.append(local_files_only)
        return "online"

    with patch(_MODULES_JSON_IS_CACHED, return_value=False):
        assert loader._load_local_first("org/model", None, load) == "online"
    assert calls == [False]


def test_load_local_first_explains_a_failed_download_of_an_uncached_model() -> None:
    """Air-gapped hosts get a clear error, not huggingface_hub's retry noise."""

    def load(local_files_only: bool) -> str:  # noqa: ARG001
        raise RuntimeError("Cannot send a request, as the client has been closed.")

    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=False),
        pytest.raises(
            loader.EmbeddingModelLoadError,
            match=r"org/model is not in the model server's Hugging Face cache",
        ) as exc_info,
    ):
        loader._load_local_first("org/model", None, load)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_load_local_first_keeps_the_online_error_of_a_cached_model() -> None:
    def load(local_files_only: bool) -> str:
        if local_files_only:
            raise OSError("partial cache")
        raise RuntimeError("Error(s) in loading state_dict")

    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        pytest.raises(RuntimeError, match="state_dict"),
    ):
        loader._load_local_first("org/model", None, load)


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
    assert loader._modules_json_is_cached("org/st-model", _SHA_A) is True
    assert loader._modules_json_is_cached("org/st-model", _SHA_B) is False
    assert loader._modules_json_is_cached("org/pinned", _SHA_B) is True
    assert loader._modules_json_is_cached("org/pinned", None) is False
    assert loader._modules_json_is_cached("org/partial", None) is False
    assert loader._modules_json_is_cached("org/plain-hf", None) is True
    assert loader._modules_json_is_cached("org/never-downloaded", None) is False
    # A local directory is not a repo id. sentence-transformers reads it directly.
    assert loader._modules_json_is_cached("/models/my-model", None) is False


def test_modules_json_is_cached_uses_sentence_transformers_home(
    tmp_path: Path, hub_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    st_home = tmp_path / "st_home"
    _make_hub_cache(st_home, "org/st-model", _SHA_A, ["modules.json"], ref_main=True)
    _make_hub_cache(hub_cache, "org/other", _SHA_A, ["modules.json"], ref_main=True)
    monkeypatch.setenv("SENTENCE_TRANSFORMERS_HOME", str(st_home))

    assert loader._modules_json_is_cached("org/st-model", None) is True
    assert loader._modules_json_is_cached("org/other", None) is False
