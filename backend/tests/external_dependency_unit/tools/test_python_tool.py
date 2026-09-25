"""Python execution preserves uploaded files, saved output, and batch fallback."""

from __future__ import annotations

import io
import json
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import UploadFile
from fastapi.background import BackgroundTasks
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

import onyx.tools.tool_implementations.python.code_interpreter_client as ci_mod
from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.models import Persona
from onyx.db.tools import get_builtin_tool
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.server.features.projects.api import upload_user_files
from onyx.server.query_and_chat.chat_backend import get_chat_session
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.streaming_models import (
    Packet,
    PythonToolDelta,
    PythonToolStart,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_chat_session,
)
from tests.external_dependency_unit.conftest import create_test_user
from tests.unit.onyx.agents.fakes import ScriptedLLM

# ---------------------------------------------------------------------------
# Mock Code Interpreter Server
# ---------------------------------------------------------------------------


class CapturedRequest:
    """A single HTTP request captured by the mock server."""

    def __init__(self, method: str, path: str, body: bytes) -> None:
        self.method = method
        self.path = path
        self.body = body

    def json_body(self) -> dict[str, Any]:
        return json.loads(self.body)


class _MockCIHandler(BaseHTTPRequestHandler):
    """HTTP handler that records every request and returns canned responses."""

    server: MockCodeInterpreterServer

    def do_POST(self) -> None:
        body = self._read_body()
        self._capture("POST", body)

        if self.path == "/v1/files":
            self.server._file_counter += 1
            self._respond_json(
                200, {"file_id": f"mock-ci-file-{self.server._file_counter}"}
            )
        elif self.path == "/v1/execute/stream":
            if self.server.streaming_enabled:
                self._respond_sse(
                    [
                        (
                            "output",
                            {"stream": "stdout", "data": "mock output\n"},
                        ),
                        (
                            "result",
                            {
                                "exit_code": 0,
                                "timed_out": False,
                                "duration_ms": 50,
                                "files": [],
                            },
                        ),
                    ]
                )
            else:
                self._respond_json(404, {"error": "not found"})
        elif self.path == "/v1/execute":
            self._respond_json(
                200,
                {
                    "stdout": "mock output\n",
                    "stderr": "",
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_ms": 50,
                    "files": [],
                },
            )
        else:
            self._respond_json(404, {"error": "not found"})

    def do_GET(self) -> None:
        self._capture("GET", b"")
        if self.path == "/health":
            self._respond_json(200, {"status": "ok"})
        else:
            self._respond_json(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        self._capture("DELETE", b"")
        self.send_response(200)
        self.end_headers()

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _capture(self, method: str, body: bytes) -> None:
        self.server.captured_requests.append(
            CapturedRequest(method=method, path=self.path, body=body)
        )

    def _respond_json(self, status: int, data: dict[str, Any]) -> None:
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _respond_sse(self, events: list[tuple[str, dict[str, Any]]]) -> None:
        frames = []
        for event_type, data in events:
            frames.append(f"event: {event_type}\ndata: {json.dumps(data)}\n\n")
        payload = "".join(frames).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class MockCodeInterpreterServer(HTTPServer):
    """HTTPServer wrapper that records requests for assertions."""

    def __init__(self) -> None:
        super().__init__(("localhost", 0), _MockCIHandler)
        self.captured_requests: list[CapturedRequest] = []
        self._file_counter = 0
        self.streaming_enabled: bool = True

    @property
    def url(self) -> str:
        host, port = self.server_address  # ty: ignore[invalid-assignment]
        return f"http://{host!s}:{port}"

    def start(self) -> None:
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def get_requests(
        self,
        method: str | None = None,
        path: str | None = None,
    ) -> list[CapturedRequest]:
        results = self.captured_requests
        if method:
            results = [r for r in results if r.method == method]
        if path:
            results = [r for r in results if r.path == path]
        return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mock_ci_server() -> Generator[MockCodeInterpreterServer, None, None]:
    server = MockCodeInterpreterServer()
    server.start()
    yield server
    server.shutdown()


@pytest.fixture(autouse=True)
def _clear_health_cache() -> None:
    """Reset the health check cache before every test."""
    import onyx.tools.tool_implementations.python.code_interpreter_client as mod

    mod._health_cache = {}


@pytest.fixture()
def _attach_python_tool_to_default_persona(db_session: Session) -> None:
    """Ensure the default persona (id=0) has the PythonTool attached."""
    persona = db_session.get(Persona, 0)
    assert persona is not None, "Default persona (id=0) not found"

    if any(tool.in_code_tool_id == "PythonTool" for tool in persona.tools):
        return
    persona.tools.append(get_builtin_tool(db_session, PythonTool))
    db_session.commit()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_code_interpreter_receives_chat_files(
    db_session: Session,
    mock_ci_server: MockCodeInterpreterServer,
    _attach_python_tool_to_default_persona: None,
    initialize_file_store: None,  # noqa: ARG001
) -> None:
    mock_ci_server.captured_requests.clear()
    mock_ci_server._file_counter = 0
    mock_url = mock_ci_server.url

    user = create_test_user(db_session, "ci_test_admin")
    chat_session = create_chat_session(db_session=db_session, user=user)

    # Upload a test CSV
    csv_content = b"name,age,city\nAlice,30,NYC\nBob,25,SF\n"
    result = upload_user_files(
        bg_tasks=BackgroundTasks(),
        files=[
            UploadFile(
                file=io.BytesIO(csv_content),
                filename="data.csv",
                size=len(csv_content),
                headers=Headers({"content-type": "text/csv"}),
            )
        ],
        project_id=None,
        temp_id_map=json.dumps({"0|data.csv": "data.csv"}),
        # Explicit: calling the endpoint directly leaves this as the Form
        # default object, which is truthy and trips the incognito guard.
        incognito_session_id=None,
        user=user,
        db_session=db_session,
    )
    assert len(result.user_files) == 1
    user_file = result.user_files[0]

    file_descriptor: FileDescriptor = {
        "id": user_file.file_id,
        "type": ChatFileType.TABULAR,
        "name": "data.csv",
        "user_file_id": str(user_file.id),
    }

    code = "import pandas as pd\ndf = pd.read_csv('data.csv')\nprint(df)"
    msg_req = SendMessageRequest(
        message="Read the CSV and print it.",
        chat_session_id=chat_session.id,
        file_descriptors=[file_descriptor],
        stream=True,
    )

    original_defaults = ci_mod.CodeInterpreterClient.__init__.__defaults__
    with (
        patch(
            "onyx.chat.prepare.get_llm_for_persona",
            return_value=ScriptedLLM(
                [
                    Delta(
                        tool_calls=[
                            ChatCompletionDeltaToolCall(
                                id="python",
                                index=0,
                                function=ResponseFunctionCall(
                                    name="run_python",
                                    arguments=json.dumps({"code": code}),
                                ),
                            )
                        ]
                    ),
                    Delta(content="The result is 4."),
                ],
                max_input_tokens=128000,
            ),
        ),
        patch(
            "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
        patch(
            "onyx.tools.tool_implementations.python.code_interpreter_client.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
    ):
        ci_mod.CodeInterpreterClient.__init__.__defaults__ = (mock_url,)
        try:
            list(handle_stream_message_objects(new_msg_req=msg_req, user=user))
        finally:
            ci_mod.CodeInterpreterClient.__init__.__defaults__ = original_defaults

    # Verify: file uploaded and code executed via streaming.
    assert len(mock_ci_server.get_requests(method="POST", path="/v1/files")) == 1
    assert (
        len(mock_ci_server.get_requests(method="POST", path="/v1/execute/stream")) == 1
    )

    # Staged input files are intentionally NOT deleted — PythonTool caches their
    # file IDs across agent-loop iterations to avoid re-uploading on every call.
    # The code interpreter cleans them up via its own TTL.
    assert len(mock_ci_server.get_requests(method="DELETE")) == 0

    execute_body = mock_ci_server.get_requests(
        method="POST", path="/v1/execute/stream"
    )[0].json_body()
    assert execute_body["code"] == code
    assert len(execute_body["files"]) == 1
    assert execute_body["files"][0]["path"] == "data.csv"


def test_code_interpreter_replay_packets_include_code_and_output(
    db_session: Session,
    mock_ci_server: MockCodeInterpreterServer,
    _attach_python_tool_to_default_persona: None,
    initialize_file_store: None,  # noqa: ARG001
) -> None:
    """Saved Python tool items preserve the executed code and output."""
    mock_ci_server.captured_requests.clear()
    mock_ci_server._file_counter = 0
    mock_url = mock_ci_server.url

    user = create_test_user(db_session, "ci_replay_test")
    chat_session = create_chat_session(db_session=db_session, user=user)

    code = 'x = 2 + 2\nprint(f"Result: {x}")'
    msg_req = SendMessageRequest(
        message="Calculate 2 + 2",
        chat_session_id=chat_session.id,
        stream=True,
    )

    original_defaults = ci_mod.CodeInterpreterClient.__init__.__defaults__
    with (
        patch(
            "onyx.chat.prepare.get_llm_for_persona",
            return_value=ScriptedLLM(
                [
                    Delta(
                        tool_calls=[
                            ChatCompletionDeltaToolCall(
                                id="python",
                                index=0,
                                function=ResponseFunctionCall(
                                    name="run_python",
                                    arguments=json.dumps({"code": code}),
                                ),
                            )
                        ]
                    ),
                    Delta(content="The result is 4."),
                ],
                max_input_tokens=128000,
            ),
        ),
        patch(
            "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
        patch(
            "onyx.tools.tool_implementations.python.code_interpreter_client.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
    ):
        ci_mod.CodeInterpreterClient.__init__.__defaults__ = (mock_url,)
        try:
            list(handle_stream_message_objects(new_msg_req=msg_req, user=user))
        finally:
            ci_mod.CodeInterpreterClient.__init__.__defaults__ = original_defaults

    # Retrieve the chat session through the same endpoint the frontend uses
    chat_detail = get_chat_session(
        session_id=chat_session.id,
        user=user,
        db_session=db_session,
    )

    assert (
        len(mock_ci_server.get_requests(method="POST", path="/v1/execute/stream")) == 1
    )

    # The response contains `packets` — a list of packet-lists, one per
    # assistant message. We should have exactly one assistant message.
    assert len(chat_detail.packets) == 1, (
        f"Expected 1 assistant packet list, got {len(chat_detail.packets)}"
    )
    packets = chat_detail.packets[0]

    starts = [
        packet.obj for packet in packets if isinstance(packet.obj, PythonToolStart)
    ]
    assert len(starts) == 1
    assert starts[0].code == code
    output = "".join(
        packet.obj.stdout
        for packet in packets
        if isinstance(packet.obj, PythonToolDelta)
    )
    assert "mock output" in output


def test_code_interpreter_streaming_fallback_to_batch(
    db_session: Session,
    mock_ci_server: MockCodeInterpreterServer,
    _attach_python_tool_to_default_persona: None,
    initialize_file_store: None,  # noqa: ARG001
) -> None:
    """When the streaming endpoint is not available (older code-interpreter),
    execute_streaming should fall back to the batch /v1/execute endpoint."""
    mock_ci_server.captured_requests.clear()
    mock_ci_server._file_counter = 0
    mock_ci_server.streaming_enabled = False
    mock_url = mock_ci_server.url

    user = create_test_user(db_session, "ci_fallback_test")
    chat_session = create_chat_session(db_session=db_session, user=user)

    code = 'print("fallback test")'
    msg_req = SendMessageRequest(
        message="Print fallback test",
        chat_session_id=chat_session.id,
        stream=True,
    )

    original_defaults = ci_mod.CodeInterpreterClient.__init__.__defaults__
    with (
        patch(
            "onyx.chat.prepare.get_llm_for_persona",
            return_value=ScriptedLLM(
                [
                    Delta(
                        tool_calls=[
                            ChatCompletionDeltaToolCall(
                                id="python",
                                index=0,
                                function=ResponseFunctionCall(
                                    name="run_python",
                                    arguments=json.dumps({"code": code}),
                                ),
                            )
                        ]
                    ),
                    Delta(content="The result is 4."),
                ],
                max_input_tokens=128000,
            ),
        ),
        patch(
            "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
        patch(
            "onyx.tools.tool_implementations.python.code_interpreter_client.CODE_INTERPRETER_BASE_URL",
            mock_url,
        ),
    ):
        ci_mod.CodeInterpreterClient.__init__.__defaults__ = (mock_url,)
        try:
            packets = list(
                handle_stream_message_objects(new_msg_req=msg_req, user=user)
            )
        finally:
            ci_mod.CodeInterpreterClient.__init__.__defaults__ = original_defaults
            mock_ci_server.streaming_enabled = True

    # Streaming was attempted first (returned 404), then fell back to batch
    assert (
        len(mock_ci_server.get_requests(method="POST", path="/v1/execute/stream")) == 1
    )
    assert len(mock_ci_server.get_requests(method="POST", path="/v1/execute")) == 1

    output = "".join(
        packet.obj.stdout
        for packet in packets
        if isinstance(packet, Packet) and isinstance(packet.obj, PythonToolDelta)
    )
    assert "mock output" in output
