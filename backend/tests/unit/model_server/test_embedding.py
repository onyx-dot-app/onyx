import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

from model_server import encoders
from model_server.encoders import embed_text, process_embed_request
from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import EmbedRequest

_CUSTOM_MODEL_NAME = "custom/embedding-model"
_NOMIC_MODEL_NAME = "nomic-ai/nomic-embed-text-v1"
_LOAD_EMBEDDING_MODEL = "model_server.encoders.load_embedding_model"


@pytest.fixture(autouse=True)
def _empty_model_cache() -> Iterator[None]:
    with (
        patch.object(encoders, "_GLOBAL_MODELS_DICT", {}),
        patch.object(encoders, "_PENDING_MODEL_JOBS", {}),
    ):
        yield


@pytest.mark.parametrize(
    ("model_name", "headroom"),
    [
        (
            DEFAULT_DOCUMENT_ENCODER_MODEL,
            encoders.REGISTRY_MODEL_PREFIX_HEADROOM_TOKENS,
        ),
        (_NOMIC_MODEL_NAME, 0),
    ],
    ids=["registry-model", "legacy-model"],
)
def test_only_registry_models_get_prefix_headroom(
    model_name: str, headroom: int
) -> None:
    """The chunker does not count a registry model's query/passage prefix, so the
    prefix must not cut off the end of a full chunk."""
    with patch(_LOAD_EMBEDDING_MODEL, return_value=MagicMock()):
        for max_context_length in (512, 2048):
            model = encoders.get_embedding_model(
                model_name, max_context_length=max_context_length
            )
            assert model.max_seq_length == max_context_length + headroom


# ---- Loading off the event loop ----


def _slow_loader(
    delay_seconds: float,
    calls: list[str],
    started: threading.Event | None = None,
) -> Callable[[str], MagicMock]:
    def load(model_name: str) -> MagicMock:
        calls.append(model_name)
        if started is not None:
            started.set()
        time.sleep(delay_seconds)
        model = MagicMock()
        model.encode.return_value = [[0.1, 0.2]]
        return model

    return load


async def _embed(model_name: str, max_context_length: int = 512) -> list[list[float]]:
    return await embed_text(
        texts=["hello"],
        model_name=model_name,
        max_context_length=max_context_length,
        normalize_embeddings=True,
        prefix=None,
    )


@pytest.mark.asyncio
async def test_model_load_does_not_block_event_loop() -> None:
    started = threading.Event()
    with patch(_LOAD_EMBEDDING_MODEL, side_effect=_slow_loader(0.3, [], started)):
        embed_task = asyncio.create_task(_embed(_CUSTOM_MODEL_NAME))

        ticks = 0
        while not embed_task.done():
            await asyncio.sleep(0.02)
            ticks += 1

        assert started.is_set()
        assert await embed_task == [[0.1, 0.2]]
    # The loop kept running while the load slept.
    assert ticks >= 5


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_load() -> None:
    """Requests for a model and context length share one load job, so waiting
    requests hold no threads. A job for another context length waits on the
    model lock and does not load the model again."""
    calls: list[str] = []
    executor = encoders._MODEL_LOAD_EXECUTOR
    with (
        patch(_LOAD_EMBEDDING_MODEL, side_effect=_slow_loader(0.3, calls)),
        patch.object(executor, "submit", wraps=executor.submit) as submit,
    ):
        results = await asyncio.gather(
            *[_embed(_CUSTOM_MODEL_NAME) for _ in range(8)],
            _embed(_CUSTOM_MODEL_NAME, max_context_length=1024),
        )

    assert results == [[[0.1, 0.2]]] * 9
    assert calls == [_CUSTOM_MODEL_NAME]
    assert submit.call_count == 2


@pytest.mark.asyncio
async def test_cancelled_request_does_not_cancel_shared_load() -> None:
    calls: list[str] = []
    with (
        ThreadPoolExecutor(max_workers=1) as busy_executor,
        patch.object(encoders, "_MODEL_LOAD_EXECUTOR", busy_executor),
        patch(_LOAD_EMBEDDING_MODEL, side_effect=_slow_loader(0.1, calls)),
    ):
        # The shared job waits in the queue. A cancel there would succeed.
        busy_executor.submit(time.sleep, 0.2)
        cancelled = asyncio.create_task(_embed(_CUSTOM_MODEL_NAME))
        kept = asyncio.create_task(_embed(_CUSTOM_MODEL_NAME))
        await asyncio.sleep(0.05)
        cancelled.cancel()

        assert await kept == [[0.1, 0.2]]
        with pytest.raises(asyncio.CancelledError):
            await cancelled

    assert calls == [_CUSTOM_MODEL_NAME]


@pytest.mark.asyncio
async def test_failed_load_is_retried_by_next_request() -> None:
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
