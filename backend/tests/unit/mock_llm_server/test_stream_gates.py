"""Browser recovery tests can hold a real provider stream at a known boundary."""

import json
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from uuid import uuid4

import httpx
import pytest

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
