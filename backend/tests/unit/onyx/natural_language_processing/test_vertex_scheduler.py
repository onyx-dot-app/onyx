import asyncio
import time
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from google.auth.credentials import Credentials
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from onyx.connectors.models import ConnectorStopSignal
from onyx.natural_language_processing.embedding_auth import build_embedding_auth
from onyx.natural_language_processing.embedding_providers import vertex_scheduler
from onyx.natural_language_processing.embedding_providers.vertex_scheduler import (
    VertexRequestScheduler,
    VertexRetrySettings,
    is_transient_vertex_error,
)
from onyx.natural_language_processing.embedding_rate_limit import EmbeddingRateLimiter
from onyx.natural_language_processing.embedding_request_policy import (
    EmbeddingRequestPolicy,
    EmbeddingRetryBackoff,
)
from onyx.natural_language_processing.search_nlp_models import CloudEmbedding
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
from shared_configs.enums import EmbeddingProvider

_KEY = "p/global/gemini-embedding-2"


def _vertex_429() -> genai_errors.ClientError:
    return genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Resource exhausted. Please try again later.",
                "status": "RESOURCE_EXHAUSTED",
            }
        },
    )


def _policy(
    should_stop: Callable[[], bool] | None = None,
    indexing: bool = True,
    rate_limiter: EmbeddingRateLimiter | None = None,
) -> EmbeddingRequestPolicy:
    return EmbeddingRequestPolicy(
        retry_backoff=EmbeddingRetryBackoff(scale_seconds=0, max_seconds=0),
        retry_tries=1,
        block_on_provider_rate_limit=indexing,
        should_stop=should_stop,
        rate_limiter=rate_limiter,
    )


def _vertex_503() -> genai_errors.ServerError:
    return genai_errors.ServerError(
        503, {"error": {"code": 503, "status": "UNAVAILABLE"}}
    )


def _scheduler_without_backoff(
    max_concurrency: int = 10, initial_concurrency: int = 10, **settings: float
) -> VertexRequestScheduler:
    return VertexRequestScheduler(
        max_concurrency=max_concurrency,
        initial_concurrency=initial_concurrency,
        settings=VertexRetrySettings(
            backoff_base_seconds=0, backoff_max_seconds=0, **settings
        ),
    )


def test_rate_limited_request_retries_under_a_lower_limit() -> None:
    scheduler = _scheduler_without_backoff()
    calls = 0

    async def request() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _vertex_429()
        return "ok"

    assert asyncio.run(scheduler.send(_KEY, request, _policy())) == "ok"
    assert calls == 3
    limit = scheduler.model_limit(_KEY)
    assert limit.limit < 10
    assert limit.in_flight == 0
    assert scheduler.process_limit.in_flight == 0


def test_rate_limit_goes_to_the_policy_after_the_budget() -> None:
    scheduler = _scheduler_without_backoff(rate_limit_retry_budget_seconds=0)
    limit = scheduler.model_limit(_KEY)
    calls = 0

    async def request() -> str:
        nonlocal calls
        calls += 1
        raise _vertex_429()

    with pytest.raises(genai_errors.ClientError):
        asyncio.run(
            scheduler._send_in_slot(request, limit, _policy(), time.monotonic())
        )
    assert calls == 1
    assert limit.limit < 10


def test_rate_limit_is_not_retried_outside_indexing() -> None:
    scheduler = _scheduler_without_backoff()
    calls = 0

    async def request() -> str:
        nonlocal calls
        calls += 1
        raise _vertex_429()

    with pytest.raises(genai_errors.ClientError):
        asyncio.run(scheduler.send(_KEY, request, _policy(indexing=False)))
    assert calls == 1


def test_stop_signal_ends_the_retries() -> None:
    scheduler = _scheduler_without_backoff()

    async def request() -> str:
        raise _vertex_429()

    with pytest.raises(ConnectorStopSignal):
        asyncio.run(scheduler.send(_KEY, request, _policy(should_stop=lambda: True)))
    assert scheduler.model_limit(_KEY).in_flight == 0
    assert scheduler.process_limit.in_flight == 0


def test_other_errors_are_raised_at_once() -> None:
    scheduler = _scheduler_without_backoff()

    async def request() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        asyncio.run(scheduler.send(_KEY, request, _policy()))
    assert scheduler.model_limit(_KEY).limit == 10
    assert scheduler.model_limit(_KEY).in_flight == 0


def test_transient_server_error_is_sent_again() -> None:
    scheduler = _scheduler_without_backoff()
    calls = 0

    async def request() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _vertex_503()
        return "ok"

    assert asyncio.run(scheduler.send(_KEY, request, _policy())) == "ok"
    assert calls == 2
    assert scheduler.model_limit(_KEY).limit == 10


def test_timeouts_are_not_sent_again() -> None:
    # These aiohttp timeouts are connection errors too.
    assert not is_transient_vertex_error(aiohttp.ConnectionTimeoutError())
    assert not is_transient_vertex_error(aiohttp.SocketTimeoutError())
    assert not is_transient_vertex_error(TimeoutError())
    assert is_transient_vertex_error(aiohttp.ServerDisconnectedError())


def test_each_resend_waits_for_the_configured_rate_limit() -> None:
    scheduler = _scheduler_without_backoff()
    limiter = MagicMock(spec=EmbeddingRateLimiter)
    limiter.acquire_async = AsyncMock()
    request = AsyncMock(side_effect=[_vertex_503(), "ok"])

    policy = _policy(rate_limiter=limiter)
    assert asyncio.run(scheduler.send(_KEY, request, policy)) == "ok"
    assert request.await_count == 2
    assert limiter.acquire_async.await_count == 2


def test_wait_for_the_configured_rate_limit_holds_no_process_slot() -> None:
    scheduler = _scheduler_without_backoff()
    slots_during_wait: list[tuple[int, int]] = []

    async def acquire(*_args: object) -> None:
        slots_during_wait.append(
            (scheduler.model_limit(_KEY).in_flight, scheduler.process_limit.in_flight)
        )

    limiter = MagicMock(spec=EmbeddingRateLimiter)
    limiter.acquire_async = acquire
    request = AsyncMock(side_effect=[_vertex_503(), "ok"])

    asyncio.run(scheduler.send(_KEY, request, _policy(rate_limiter=limiter)))
    # (model slots, process slots): before the request, and before the resend.
    assert slots_during_wait == [(1, 0), (1, 0)]


def test_rate_limited_request_backs_off_inside_its_model_slot() -> None:
    scheduler = _scheduler_without_backoff(max_concurrency=1, initial_concurrency=1)
    in_flight_during_backoff: list[tuple[int, int]] = []
    calls = 0

    async def request() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _vertex_429()
        return "ok"

    async def backoff(_seconds: float) -> None:
        in_flight_during_backoff.append(
            (scheduler.model_limit(_KEY).in_flight, scheduler.process_limit.in_flight)
        )

    with patch.object(vertex_scheduler.asyncio, "sleep", backoff):
        asyncio.run(scheduler.send(_KEY, request, _policy()))
    # (model slots, process slots): only a request in flight holds a process slot.
    assert in_flight_during_backoff == [(1, 0)]
    assert scheduler.model_limit(_KEY).in_flight == 0
    assert scheduler.process_limit.in_flight == 0


def test_waiting_for_a_slot_sees_a_stop_signal() -> None:
    scheduler = _scheduler_without_backoff(
        max_concurrency=1, initial_concurrency=1, stop_check_interval_seconds=0.01
    )

    async def scenario() -> None:
        await scheduler.process_limit.acquire()
        await scheduler.send(_KEY, AsyncMock(), _policy(should_stop=lambda: True))

    with pytest.raises(ConnectorStopSignal):
        asyncio.run(scenario())
    # The scenario holds the only process slot itself.
    assert scheduler.model_limit(_KEY).in_flight == 0
    assert scheduler.process_limit.in_flight == 1


def test_process_limit_holds_over_models() -> None:
    scheduler = _scheduler_without_backoff(max_concurrency=2, initial_concurrency=2)
    peak = 0
    started = 0

    async def scenario() -> None:
        two_running = asyncio.Event()
        release = asyncio.Event()

        async def request() -> str:
            nonlocal peak, started
            started += 1
            peak = max(peak, scheduler.process_limit.in_flight)
            if started == 2:
                two_running.set()
            await release.wait()
            return "ok"

        sends = [
            asyncio.create_task(
                scheduler.send(f"p/global/model-{i}", request, _policy())
            )
            for i in range(4)
        ]
        await asyncio.wait_for(two_running.wait(), timeout=5)
        release.set()
        await asyncio.gather(*sends)

    asyncio.run(scenario())
    assert started == 4
    assert peak == 2


def _cloud_embedding() -> CloudEmbedding:
    auth = build_embedding_auth(
        EmbeddingProvider.GOOGLE,
        None,
        VertexEmbeddingConfig(
            auth_method="workload_identity", project_id="p", location="global"
        ),
    )
    return CloudEmbedding(
        api_key=None, provider=EmbeddingProvider.GOOGLE, auth=auth, policy=_policy()
    )


def _embed(
    client: MagicMock, texts: list[str], model: str = "gemini-embedding-2"
) -> None:
    with (
        patch("google.auth.default", return_value=(MagicMock(spec=Credentials), "p")),
        patch("google.genai.Client", return_value=client),
    ):
        asyncio.run(
            _cloud_embedding()._embed_vertex(
                texts=texts,
                model=model,
                embedding_type="RETRIEVAL_DOCUMENT",
                reduced_dimension=None,
            )
        )


def test_failed_call_gives_back_every_slot(
    vertex_scheduler: VertexRequestScheduler,
) -> None:
    # The TaskGroup cancels sibling requests while they hold slots.
    calls = 0

    async def embed_content(**_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("boom")
        await asyncio.Event().wait()
        return None

    client = MagicMock()
    client.aio.models.embed_content = embed_content
    client.aio.aclose = AsyncMock()
    with pytest.raises(RuntimeError):
        _embed(client, ["a", "b", "c", "d"])

    assert vertex_scheduler.model_limit(_KEY).in_flight == 0
    assert vertex_scheduler.process_limit.in_flight == 0


def test_embed_call_raises_the_request_error_not_a_group() -> None:
    client = MagicMock()
    client.aio.models.embed_content = AsyncMock(side_effect=ConnectorStopSignal("stop"))
    client.aio.aclose = AsyncMock()
    with pytest.raises(ConnectorStopSignal):
        _embed(client, ["a", "b", "c"])


def test_stop_signal_is_raised_before_an_error_that_is_retried() -> None:
    # Both requests fail before the TaskGroup cancels one of them. The
    # RuntimeError is first in the group.
    both_started = asyncio.Event()
    calls = 0

    async def embed_content(**_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            await both_started.wait()
            raise ConnectorStopSignal("stop")
        both_started.set()
        raise RuntimeError("boom")

    client = MagicMock()
    client.aio.models.embed_content = embed_content
    client.aio.aclose = AsyncMock()
    with pytest.raises(ConnectorStopSignal):
        _embed(client, ["a", "b"])


def test_each_name_of_a_model_shares_one_limit(
    vertex_scheduler: VertexRequestScheduler,
) -> None:
    response = MagicMock()
    response.embeddings = [MagicMock(values=[1.0])]
    client = MagicMock()
    client.aio.models.embed_content = AsyncMock(return_value=response)
    client.aio.aclose = AsyncMock()
    limit = vertex_scheduler.model_limit(_KEY)
    before = limit.limit

    _embed(client, ["a"], model="publishers/google/models/gemini-embedding-2")

    # The success counted on the limit of the base model.
    assert limit.limit == before + 1


def test_embeddings_keep_the_input_order() -> None:
    async def scenario() -> list[list[float]]:
        last_done = asyncio.Event()

        async def embed_content(
            contents: list[genai_types.Content], **_kwargs: object
        ) -> MagicMock:
            parts = contents[0].parts or []
            text = (parts[0].text or "").removeprefix("title: none | text: ")
            # The last input finishes first.
            if text == "ccc":
                last_done.set()
            else:
                await last_done.wait()
            response = MagicMock()
            response.embeddings = [MagicMock(values=[float(len(text))])]
            return response

        client = MagicMock()
        client.aio.models.embed_content = embed_content
        client.aio.aclose = AsyncMock()
        with (
            patch(
                "google.auth.default",
                return_value=(MagicMock(spec=Credentials), "p"),
            ),
            patch("google.genai.Client", return_value=client),
        ):
            return await _cloud_embedding()._embed_vertex(
                texts=["a", "bb", "ccc"],
                model="gemini-embedding-2",
                embedding_type="RETRIEVAL_DOCUMENT",
                reduced_dimension=None,
            )

    # The timeout fails the test if the requests do not run in parallel.
    embeddings = asyncio.run(asyncio.wait_for(scenario(), timeout=10))
    assert embeddings == [[1.0], [2.0], [3.0]]
