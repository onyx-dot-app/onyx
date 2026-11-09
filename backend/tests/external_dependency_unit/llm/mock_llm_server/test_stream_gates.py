"""Browser recovery tests can hold a real provider stream at a known boundary."""

import json
from collections.abc import Awaitable, Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from queue import Empty, Queue
from threading import Event
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from starlette.requests import Request

from tests.integration.mock_services.mock_llm_server.models import Reply, Script


@pytest.mark.parametrize("release_method", ["release", "delete", "replace"])
def test_stream_waits_after_first_chunk_and_cleanup_releases_it(
    mock_llm_server: str, release_method: str
) -> None:
    script_url = f"{mock_llm_server}/scripts/{uuid4().hex}"
    gate_url = f"{script_url}/gates/paused/release"
    chunks: Queue[str] = Queue()
    script = Script(
        default_reply=Reply(text="first secondthird ", pause_after_first_chunk="paused")
    )
    httpx.put(script_url, json=script.model_dump(mode="json")).raise_for_status()

    def consume() -> str:
        content = ""
        with httpx.stream(
            "POST",
            f"{script_url}/v1/chat/completions",
            json={"model": "mock", "messages": [], "stream": True},
            timeout=10,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                delta = json.loads(line[6:])["choices"][0]["delta"]
                if piece := delta.get("content"):
                    chunks.put(piece)
                    content += piece
        return content

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(consume)
        try:
            assert chunks.get(timeout=5) == "first "
            with pytest.raises(Empty):
                chunks.get(timeout=0.1)
            if release_method == "release":
                httpx.post(gate_url).raise_for_status()
            elif release_method == "replace":
                httpx.put(
                    script_url, json=Script().model_dump(mode="json")
                ).raise_for_status()
            else:
                httpx.delete(script_url).raise_for_status()
            assert result.result(timeout=5) == "first secondthird "
        finally:
            # Release even on failed assertions so the test cannot strand a worker.
            httpx.delete(script_url).raise_for_status()


@pytest.mark.parametrize("cleanup", ["delete", "replace"])
def test_cleanup_while_request_body_arrives(mock_llm_server: str, cleanup: str) -> None:
    script_url: str = f"{mock_llm_server}/scripts/{uuid4().hex}"
    script: Script = Script(
        default_reply=Reply(text="stale", pause_after_first_chunk="late")
    )
    httpx.put(script_url, json=script.model_dump(mode="json")).raise_for_status()
    body_started: Event = Event()
    resume_body: Event = Event()
    original_json: Callable[[Request], Awaitable[Any]] = Request.json

    async def read_json(request: Request) -> Any:
        body_started.set()
        return await original_json(request)

    def body() -> Iterator[bytes]:
        yield b'{"model":"mock",'
        if not resume_body.wait(timeout=5):
            raise TimeoutError("request body was not released")
        yield b'"messages":[],"stream":true}'

    def complete() -> httpx.Response:
        return httpx.post(
            f"{script_url}/v1/chat/completions", content=body(), timeout=5
        )

    with (
        patch.object(Request, "json", read_json),
        patch(
            "tests.integration.mock_services.mock_llm_server.server._GATE_TIMEOUT_S",
            0.05,
        ),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        result: Future[httpx.Response] = executor.submit(complete)
        try:
            assert body_started.wait(timeout=5)
            if cleanup == "delete":
                httpx.delete(script_url).raise_for_status()
            else:
                replacement: Script = Script(default_reply=Reply(text="current"))
                httpx.put(
                    script_url, json=replacement.model_dump(mode="json")
                ).raise_for_status()
            resume_body.set()
            response: httpx.Response = result.result(timeout=5)
            if cleanup == "delete":
                assert response.status_code == 400
                assert "unknown script" in response.text
            else:
                response.raise_for_status()
                text: str = "".join(
                    json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                    for line in response.text.splitlines()
                    if line.startswith("data: ") and line != "data: [DONE]"
                )
                assert text == "current"
        finally:
            resume_body.set()
            httpx.delete(script_url).raise_for_status()
