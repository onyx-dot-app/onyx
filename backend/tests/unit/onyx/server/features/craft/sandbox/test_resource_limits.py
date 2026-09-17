import io
import json
import subprocess
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from docx import Document
from docx.oxml.numbering import CT_Numbering
from mitmproxy import http

from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.db.models import ExternalApp
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.graphql_parsing import (
    GraphQLParsingLimitError,
    parse_invocations,
)
from onyx.sandbox_proxy import request_evaluator
from onyx.server.features.build.sandbox import base, snapshot_manager
from onyx.server.features.build.sandbox.docker import docker_sandbox_manager as docker
from onyx.server.features.build.sandbox.kubernetes import (
    kubernetes_sandbox_manager as kubernetes,
)
from onyx.server.features.build.sandbox.opencode import event_bus
from onyx.server.features.build.session import md_to_docx


@pytest.mark.parametrize("backend", ["docker", "kubernetes"])
def test_sandbox_download_bounds_actual_read(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = uuid4()
    sandbox_id = uuid4()
    monkeypatch.setattr(base, "MAX_DOWNLOAD_FILE_SIZE_BYTES", 8)
    monkeypatch.setattr(docker, "MAX_DOWNLOAD_FILE_SIZE_BYTES", 8)
    monkeypatch.setattr(kubernetes, "MAX_DOWNLOAD_FILE_SIZE_BYTES", 8)
    output_sizes: list[int] = []

    def execute(command: list[str]) -> str:
        script = command[2].replace(f"/workspace/sessions/{session_id}", str(tmp_path))
        result = subprocess.run(command[:2] + [script], capture_output=True, check=True)
        output_sizes.append(len(result.stdout))
        return result.stdout.decode()

    def docker_exec(
        _container: Any, command: list[str], **_kwargs: Any
    ) -> docker.ExecResult:
        return docker.ExecResult(0, execute(command).encode(), b"")

    def kubernetes_exec(*_args: Any, **kwargs: Any) -> str:
        return execute(kwargs["command"])

    monkeypatch.setattr(docker, "_run_in_container_as_sandbox_user", docker_exec)
    monkeypatch.setattr(kubernetes, "k8s_stream", kubernetes_exec)
    docker_manager = object.__new__(docker.DockerSandboxManager)
    kubernetes_manager = object.__new__(kubernetes.KubernetesSandboxManager)
    with (
        patch.object(docker_manager, "_require_container", return_value=MagicMock()),
        patch.object(kubernetes_manager, "_get_pod_name", return_value="test-pod"),
        patch.object(kubernetes_manager, "_stream_core_api", create=True),
        patch.object(kubernetes_manager, "_namespace", "test", create=True),
    ):
        manager = docker_manager if backend == "docker" else kubernetes_manager
        file = tmp_path / "result.bin"
        file.write_bytes(b"a" * 8)
        assert manager.read_file(sandbox_id, session_id, "result.bin") == b"a" * 8
        for size in (9, 10000):
            file.write_bytes(b"a" * size)
            with pytest.raises(OnyxError):
                manager.read_file(sandbox_id, session_id, "result.bin")
        assert max(output_sizes) <= 13


def test_snapshot_copy_rejects_overflow_before_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(snapshot_manager, "_MAX_SNAPSHOT_ARCHIVE_BYTES", 8)
    monkeypatch.setattr(snapshot_manager, "_SNAPSHOT_COPY_CHUNK_BYTES", 4)
    exact = io.BytesIO()
    assert snapshot_manager._copy_snapshot_stream(io.BytesIO(b"a" * 8), exact) == 8
    target = io.BytesIO()
    with pytest.raises(RuntimeError, match="snapshot archive exceeds"):
        snapshot_manager._copy_snapshot_stream(io.BytesIO(b"a" * 9), target)
    assert target.getvalue() == b"a" * 8


@pytest.mark.parametrize("terminated", [False, True])
def test_sse_event_limit(monkeypatch: pytest.MonkeyPatch, terminated: bool) -> None:
    monkeypatch.setattr(event_bus, "_MAX_SSE_BUFFER_CHARS", 32)
    bus = event_bus.PodEventBus(base_url="http://test.invalid", auth=None)
    response = MagicMock()
    oversized = (
        ['data: {"type": "hidden", "p": "' + "x" * 33 + '"}\n\n']
        if terminated
        else ["x" * 33, "y" * 40 + '\ndata: {"type": "hidden"}\n', "\n"]
    )
    response.iter_text.return_value = iter(
        ["data: {}\n\n" * 10, *oversized, 'data: {"type": "after"}\n\n']
    )
    with (
        patch.object(event_bus.httpx, "stream") as stream,
        patch.object(bus, "_dispatch") as dispatch,
    ):
        stream.return_value.__enter__.return_value = response
        bus._read_one_stream()
        assert dispatch.call_count == 11
        dispatch.assert_called_with({"type": "after"})
    bus.close()


def test_sse_skipped_tail_memory_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(event_bus, "_MAX_SSE_BUFFER_CHARS", 32)
    bus = event_bus.PodEventBus(base_url="http://test.invalid", auth=None)
    response = MagicMock()
    response.iter_text.return_value = ("x" * 1024 for _ in range(2048))
    with patch.object(event_bus.httpx, "stream") as stream:
        stream.return_value.__enter__.return_value = response
        tracemalloc.start()
        try:
            bus._read_one_stream()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert peak < 512 * 1024
    bus.close()


def test_docx_numbering_scans_existing_ids_once() -> None:
    document = Document()
    original = CT_Numbering.findall
    scans = 0

    def findall(self: CT_Numbering, path: str, *args: Any, **kwargs: Any) -> Any:
        nonlocal scans
        if path == md_to_docx.qn("w:num"):
            scans += 1
        return original(self, path, *args, **kwargs)

    with patch.object(CT_Numbering, "findall", findall):
        ids = [
            md_to_docx._create_list_numbering(document, "List Number", 1)
            for _ in range(20)
        ]
    assert None not in ids
    assert len(set(ids)) == 20
    assert scans == 1


@pytest.mark.parametrize(
    "body",
    [
        b"[" * 10000 + b"0" + b"]" * 10000,
        json.dumps({"query": "{ f " * 2000 + "}" * 2000}).encode(),
        json.dumps(
            {
                "query": "query { ...F0 } "
                + " ".join(
                    f"fragment F{i} on Query {{ ...F{i + 1} }}" for i in range(2000)
                )
                + " fragment F2000 on Query { secret }"
            }
        ).encode(),
    ],
    ids=["json-depth", "graphql-depth", "fragment-depth"],
)
def test_graphql_recursion_rejects_request(body: bytes) -> None:
    with pytest.raises(GraphQLParsingLimitError):
        parse_invocations(body)


def test_deep_json_payload_does_not_raise() -> None:
    assert (
        request_evaluator._decode_body(
            b"[" * 10000 + b"0" + b"]" * 10000, "application/json"
        )
        is None
    )


def test_graphql_limit_returns_deny() -> None:
    app = ExternalApp(id=1, name="Test", app_type=ExternalAppType.CUSTOM)
    request = http.Request.make("POST", "https://example.com/graphql", b"{}")
    with (
        patch.object(request_evaluator, "get_session_with_tenant"),
        patch.object(request_evaluator, "get_external_apps", return_value=[app]),
        patch.object(request_evaluator, "resolve_app_for_url", return_value=app),
        patch.object(
            request_evaluator, "recognize_actions", side_effect=GraphQLParsingLimitError
        ),
    ):
        result = request_evaluator.ExternalAppRequestEvaluator().evaluate(
            request, "test", uuid4()
        )
    assert result is not None
    assert result.governing_action.policy is EndpointPolicy.DENY


def test_sse_dispatches_small_event_before_next_chunk() -> None:
    class PausedStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b'data: {"type": "message.updated"}\n\n'
            raise RuntimeError("waiting for the next event")

    bus = event_bus.PodEventBus(base_url="http://test.invalid", auth=None)
    response = httpx.Response(
        200,
        stream=PausedStream(),
        request=httpx.Request("GET", "http://test.invalid/event"),
    )
    with (
        patch.object(event_bus.httpx, "stream") as stream,
        patch.object(bus, "_dispatch") as dispatch,
    ):
        stream.return_value.__enter__.return_value = response
        with pytest.raises(RuntimeError, match="waiting for the next event"):
            bus._read_one_stream()
        dispatch.assert_called_once_with({"type": "message.updated"})
    response.close()
    bus.close()
