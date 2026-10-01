import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from model_server import encoders
from model_server.embedding_model_loader import EmbeddingModelLoadError
from model_server.encoders import embed_text, process_embed_request
from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from shared_configs.embedding_models import get_local_model_spec
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import EmbedRequest

_CUSTOM_MODEL_NAME = "custom/embedding-model"
_NOMIC_MODEL_NAME = "nomic-ai/nomic-embed-text-v1"
_E5_MODEL_NAME = "intfloat/e5-base-v2"
_LEGACY_AND_CUSTOM_NAMES = [_NOMIC_MODEL_NAME, _E5_MODEL_NAME, _CUSTOM_MODEL_NAME]
_MODULES_JSON_IS_CACHED = "model_server.embedding_model_loader._modules_json_is_cached"
_ST_CLASS = "sentence_transformers.SentenceTransformer"
_LOAD_EMBEDDING_MODEL = "model_server.encoders.load_embedding_model"


@pytest.fixture(autouse=True)
def _empty_model_cache() -> Iterator[None]:
    with (
        patch.object(encoders, "_GLOBAL_MODELS_DICT", {}),
        patch.object(encoders, "_PENDING_MODEL_JOBS", {}),
    ):
        yield


def _legacy_call(model_name: str, local_files_only: bool) -> dict[str, Any]:
    """The kwargs of the load call from before the registry, except local_files_only."""
    return {
        "model_name_or_path": model_name,
        "local_files_only": local_files_only,
        "trust_remote_code": False,
    }


def _fake_model(dim: int = 2) -> MagicMock:
    model = MagicMock()
    model.encode.return_value = np.zeros((1, dim))
    return model


# ---- Legacy and custom names: the exact old call, local first ----


@pytest.mark.parametrize("model_name", _LEGACY_AND_CUSTOM_NAMES)
def test_legacy_model_loads_from_local_cache_first(model_name: str) -> None:
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, return_value=_fake_model()) as load,
    ):
        model = encoders.get_embedding_model(model_name, max_context_length=512)

    load.assert_called_once_with(**_legacy_call(model_name, local_files_only=True))
    assert model.max_seq_length == 512


@pytest.mark.parametrize("model_name", _LEGACY_AND_CUSTOM_NAMES)
def test_legacy_model_not_in_cache_loads_online(model_name: str) -> None:
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=False),
        patch(_ST_CLASS, return_value=_fake_model()) as load,
    ):
        encoders.get_embedding_model(model_name, max_context_length=512)

    load.assert_called_once_with(**_legacy_call(model_name, local_files_only=False))


@pytest.mark.parametrize(
    "cache_error",
    [
        OSError("couldn't find them in the cached files"),
        OSError("does not appear to have a file named model.safetensors"),
        ValueError("Unrecognized processing class"),
        TypeError("missing 1 required positional argument: 'embedding_dimension'"),
    ],
)
def test_legacy_model_partial_cache_retries_online(cache_error: Exception) -> None:
    model = _fake_model()
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, side_effect=[cache_error, model]) as load,
    ):
        loaded = encoders.get_embedding_model(_NOMIC_MODEL_NAME, max_context_length=512)

    assert loaded is model
    assert [c.kwargs for c in load.call_args_list] == [
        _legacy_call(_NOMIC_MODEL_NAME, local_files_only=True),
        _legacy_call(_NOMIC_MODEL_NAME, local_files_only=False),
    ]


def test_legacy_model_real_load_error_is_not_retried() -> None:
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, side_effect=RuntimeError("CUDA out of memory")) as load,
        pytest.raises(RuntimeError, match="CUDA out of memory"),
    ):
        encoders.get_embedding_model(_NOMIC_MODEL_NAME, max_context_length=512)

    assert load.call_count == 1
    assert encoders.model_key(_NOMIC_MODEL_NAME) not in encoders._GLOBAL_MODELS_DICT


def test_default_model_uses_registry_loader() -> None:
    """The bundled default is a registry model: pinned revision, local first."""
    spec = get_local_model_spec(DEFAULT_DOCUMENT_ENCODER_MODEL)
    assert spec is not None
    with (
        patch(_MODULES_JSON_IS_CACHED, return_value=True),
        patch(_ST_CLASS, return_value=_fake_model(spec.model_dim)) as load,
    ):
        encoders.get_embedding_model(spec.model_name, max_context_length=512)

    load.assert_called_once()
    assert load.call_args.kwargs["revision"] == spec.hf_revision
    assert load.call_args.kwargs["local_files_only"] is True
    assert load.call_args.kwargs["trust_remote_code"] is False


# ---- max_seq_length ----


def test_registry_model_gets_prefix_headroom() -> None:
    spec = get_local_model_spec(DEFAULT_DOCUMENT_ENCODER_MODEL)
    assert spec is not None
    with patch(_LOAD_EMBEDDING_MODEL, return_value=_fake_model(spec.model_dim)):
        model = encoders.get_embedding_model(spec.model_name, max_context_length=512)
        assert (
            model.max_seq_length == 512 + encoders.REGISTRY_MODEL_PREFIX_HEADROOM_TOKENS
        )

        model = encoders.get_embedding_model(spec.model_name, max_context_length=2048)
        assert (
            model.max_seq_length
            == 2048 + encoders.REGISTRY_MODEL_PREFIX_HEADROOM_TOKENS
        )


def test_registry_name_with_another_stored_dim_has_no_headroom() -> None:
    """A custom model with a registry name keeps the legacy load and the legacy
    max_seq_length."""
    spec = get_local_model_spec("voyageai/voyage-4-nano")
    assert spec is not None
    model = _fake_model(1024)
    with patch(_LOAD_EMBEDDING_MODEL, return_value=model) as load:
        encoders.get_embedding_model(
            spec.model_name, max_context_length=512, expected_dim=1024
        )

    load.assert_called_once_with(spec.model_name, 1024)
    assert model.max_seq_length == 512


def test_legacy_and_registry_loads_of_one_name_are_cached_separately() -> None:
    """A re-index from a custom voyage-4-nano (1024 dims) to the registry
    voyage-4-nano (2048 dims) needs both loads at the same time."""
    spec = get_local_model_spec("voyageai/voyage-4-nano")
    assert spec is not None
    custom_model = _fake_model(1024)
    registry_model = _fake_model(spec.model_dim)
    with patch(
        _LOAD_EMBEDDING_MODEL, side_effect=[custom_model, registry_model]
    ) as load:
        for _ in range(2):
            assert (
                encoders.get_embedding_model(
                    spec.model_name, max_context_length=512, expected_dim=1024
                )
                is custom_model
            )
            assert (
                encoders.get_embedding_model(
                    spec.model_name,
                    max_context_length=512,
                    expected_dim=spec.model_dim,
                )
                is registry_model
            )
            # An API server without the field gets the registry load.
            assert (
                encoders.get_embedding_model(spec.model_name, max_context_length=512)
                is registry_model
            )

    assert load.call_count == 2
    assert custom_model.max_seq_length == 512
    assert (
        registry_model.max_seq_length
        == 512 + encoders.REGISTRY_MODEL_PREFIX_HEADROOM_TOKENS
    )


def test_legacy_model_max_seq_length_and_prewarm_unchanged() -> None:
    model = _fake_model()
    with patch(_LOAD_EMBEDDING_MODEL, return_value=model):
        encoders.get_embedding_model(_NOMIC_MODEL_NAME, max_context_length=512)
        assert model.max_seq_length == 512
        # The load pre-warms once at the context length.
        assert model.encode.call_count == 1
        assert model.encode.call_args.args[0] == ["x " * 1024]

        encoders.get_embedding_model(_NOMIC_MODEL_NAME, max_context_length=512)
        assert model.encode.call_count == 1

        encoders.get_embedding_model(_NOMIC_MODEL_NAME, max_context_length=2048)
        assert model.max_seq_length == 2048
        assert model.encode.call_count == 2


# ---- Failed loads ----


def test_failed_load_is_not_cached_and_is_retried() -> None:
    model = _fake_model()
    with patch(
        _LOAD_EMBEDDING_MODEL,
        side_effect=[EmbeddingModelLoadError("wrong dim"), model],
    ) as load:
        with pytest.raises(EmbeddingModelLoadError, match="wrong dim"):
            encoders.get_embedding_model(_CUSTOM_MODEL_NAME, max_context_length=512)
        assert (
            encoders.model_key(_CUSTOM_MODEL_NAME) not in encoders._GLOBAL_MODELS_DICT
        )

        assert (
            encoders.get_embedding_model(_CUSTOM_MODEL_NAME, max_context_length=512)
            is model
        )
    assert load.call_count == 2


# ---- Loading off the event loop ----


def _slow_loader(
    delay_seconds: float,
    started: threading.Event | None = None,
    calls: list[str] | None = None,
) -> Callable[[str], MagicMock]:
    def load(model_name: str, _expected_dim: int | None = None) -> MagicMock:
        if calls is not None:
            calls.append(model_name)
        if started is not None:
            started.set()
        time.sleep(delay_seconds)
        model = MagicMock()
        model.encode.return_value = [[0.1, 0.2]]
        return model

    return load


async def _embed(model_name: str) -> list[list[float]]:
    return await embed_text(
        texts=["hello"],
        model_name=model_name,
        max_context_length=512,
        normalize_embeddings=True,
        prefix=None,
    )


@pytest.mark.asyncio
async def test_model_load_does_not_block_event_loop() -> None:
    started = threading.Event()
    with patch(_LOAD_EMBEDDING_MODEL, side_effect=_slow_loader(1.0, started)):
        embed_task = asyncio.create_task(_embed(_CUSTOM_MODEL_NAME))

        tick_start = time.monotonic()
        ticks = 0
        while not embed_task.done():
            await asyncio.sleep(0.02)
            ticks += 1
        elapsed = time.monotonic() - tick_start

        assert started.is_set()
        assert await embed_task == [[0.1, 0.2]]
    # The loop kept running while the load slept for 1 second.
    assert elapsed >= 0.9
    assert ticks >= 20


@pytest.mark.asyncio
async def test_concurrent_first_requests_load_model_once() -> None:
    calls: list[str] = []
    with patch(_LOAD_EMBEDDING_MODEL, side_effect=_slow_loader(0.3, calls=calls)):
        results = await asyncio.gather(*[_embed(_CUSTOM_MODEL_NAME) for _ in range(8)])

        # A later request uses the cached model with no new load.
        await _embed(_CUSTOM_MODEL_NAME)

    assert calls == [_CUSTOM_MODEL_NAME]
    assert results == [[[0.1, 0.2]]] * 8


def test_concurrent_threads_load_model_once() -> None:
    calls: list[str] = []
    loaded: list[Any] = []
    with patch(_LOAD_EMBEDDING_MODEL, side_effect=_slow_loader(0.3, calls=calls)):
        threads = [
            threading.Thread(
                target=lambda: loaded.append(
                    encoders.get_embedding_model(
                        _CUSTOM_MODEL_NAME, max_context_length=512
                    )
                )
            )
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert calls == [_CUSTOM_MODEL_NAME]
    assert len(loaded) == 4
    assert all(model is loaded[0] for model in loaded)


@pytest.mark.asyncio
async def test_different_models_load_in_parallel() -> None:
    calls: list[str] = []
    with patch(_LOAD_EMBEDDING_MODEL, side_effect=_slow_loader(0.5, calls=calls)):
        start = time.monotonic()
        await asyncio.gather(_embed("custom/model-a"), _embed("custom/model-b"))
        elapsed = time.monotonic() - start

    assert sorted(calls) == ["custom/model-a", "custom/model-b"]
    assert elapsed < 0.9


@pytest.mark.asyncio
async def test_cancelled_request_does_not_cancel_shared_load() -> None:
    calls: list[str] = []
    with patch(_LOAD_EMBEDDING_MODEL, side_effect=_slow_loader(0.3, calls=calls)):
        cancelled = asyncio.create_task(_embed(_CUSTOM_MODEL_NAME))
        kept = asyncio.create_task(_embed(_CUSTOM_MODEL_NAME))
        await asyncio.sleep(0.05)
        cancelled.cancel()

        assert await kept == [[0.1, 0.2]]
        with pytest.raises(asyncio.CancelledError):
            await cancelled

    assert calls == [_CUSTOM_MODEL_NAME]


@pytest.mark.asyncio
async def test_failed_async_load_is_retried_by_next_request() -> None:
    model = MagicMock()
    model.encode.return_value = [[0.1, 0.2]]
    with patch(
        _LOAD_EMBEDDING_MODEL, side_effect=[OSError("network down"), model]
    ) as load:
        with pytest.raises(OSError, match="network down"):
            await _embed(_CUSTOM_MODEL_NAME)
        assert await _embed(_CUSTOM_MODEL_NAME) == [[0.1, 0.2]]

    assert load.call_count == 2
    assert encoders._PENDING_MODEL_JOBS == {}


# ---- embed_text / process_embed_request ----


@pytest.mark.asyncio
async def test_embed_text_no_model_name() -> None:
    # Test that the function raises an error when no model name is provided
    with pytest.raises(
        ValueError,
        match="Model name must be provided to run embeddings",
    ):
        await embed_text(
            texts=["test1", "test2"],
            model_name=None,
            max_context_length=512,
            normalize_embeddings=True,
            prefix=None,
        )


@pytest.mark.asyncio
async def test_embed_text_local_model() -> None:
    with patch("model_server.encoders.get_embedding_model") as mock_get_model:
        mock_model = MagicMock()
        mock_model.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]
        mock_get_model.return_value = mock_model

        result = await embed_text(
            texts=["test1", "test2"],
            model_name="fake-local-model",
            max_context_length=512,
            normalize_embeddings=True,
            prefix=None,
        )

        assert result == [[0.1, 0.2], [0.3, 0.4]]
        mock_model.encode.assert_called_once()


@pytest.mark.asyncio
async def test_embed_request_passes_the_stored_dim_to_the_loader() -> None:
    request = EmbedRequest(
        texts=["hello"],
        model_name="voyageai/voyage-4-nano",
        max_context_length=512,
        normalize_embeddings=True,
        text_type=EmbedTextType.PASSAGE,
        expected_dim=1024,
    )
    model = MagicMock()
    model.encode.return_value = [[0.1, 0.2]]
    with patch(_LOAD_EMBEDDING_MODEL, return_value=model) as load:
        await process_embed_request(request)

    load.assert_called_once_with("voyageai/voyage-4-nano", 1024)


@pytest.mark.asyncio
async def test_concurrent_embeddings() -> None:
    def mock_encode(
        *args: Any,  # noqa: ARG001
        **kwargs: Any,  # noqa: ARG001
    ) -> List[List[float]]:
        time.sleep(5)
        return [[0.1, 0.2, 0.3]]

    test_req = EmbedRequest(
        texts=["test"],
        model_name="'nomic-ai/nomic-embed-text-v1'",
        deployment_name=None,
        max_context_length=512,
        normalize_embeddings=True,
        api_key=None,
        provider_type=None,
        text_type=EmbedTextType.QUERY,
        manual_query_prefix=None,
        manual_passage_prefix=None,
        api_url=None,
        api_version=None,
        reduced_dimension=None,
    )

    # process_embed_request imports litellm on first use, which takes seconds.
    # Import it before the clock starts so the test only measures the embeds.
    import litellm.exceptions  # noqa: F401

    with patch("model_server.encoders.get_embedding_model") as mock_get_model:
        mock_model = MagicMock()
        mock_model.encode = mock_encode
        mock_get_model.return_value = mock_model
        start_time = time.time()

        tasks = [process_embed_request(test_req) for _ in range(5)]
        await asyncio.gather(*tasks)

        end_time = time.time()

        # 5 * 5 seconds = 25 seconds, this test ensures that the embeddings are at least yielding the thread
        # However, the developer may still introduce unnecessary blocking above the mock and this test will
        # still pass as long as it's less than (7 - 5) / 5 seconds
        assert end_time - start_time < 7
