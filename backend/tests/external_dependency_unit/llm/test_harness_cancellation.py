"""Exercise real LiteLLM HTTP connections without external provider credentials."""

import json
import select
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import GenerationRequest, TextDeltaEvent, UserMessage
from onyx.llm.multi_llm import LitellmLLM, LitellmTransport
from onyx.tracing.flows import LLMFlow


class ProviderState:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.disconnected = threading.Event()
        self.release = threading.Event()
        self.requests = 0


def _first_events(provider: str) -> bytes:
    if provider == "responses":
        events = [
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {
                    "id": "resp_test",
                    "object": "response",
                    "created_at": 1,
                    "model": "gpt-5-mini",
                    "status": "in_progress",
                    "output": [],
                },
            },
            {
                "type": "response.output_item.added",
                "sequence_number": 1,
                "output_index": 0,
                "item": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "status": "in_progress",
                },
            },
            {
                "type": "response.output_text.delta",
                "sequence_number": 2,
                "item_id": "msg_test",
                "output_index": 0,
                "content_index": 0,
                "delta": "hello",
            },
        ]
        return "".join(
            f"event: {body['type']}\ndata: {json.dumps(body)}\n\n" for body in events
        ).encode()
    if provider == "anthropic":
        events = [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": "claude-haiku-4-5",
                        "usage": {"input_tokens": 1, "output_tokens": 0},
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "hello"},
                },
            ),
        ]
        return "".join(
            f"event: {name}\ndata: {json.dumps(body)}\n\n" for name, body in events
        ).encode()
    chunk = {
        "id": "chat-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "harness-model",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "hello"},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n".encode()


@contextmanager
def provider_server(
    provider: str, send_chunk: bool, complete: bool = False
) -> Iterator[tuple[str, ProviderState]]:
    state = ProviderState()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            state.requests += 1
            state.started.set()
            if send_chunk:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(_first_events(provider))
                if complete:
                    self.wfile.write(
                        b'data: {"id":"chat-test","object":"chat.completion.chunk","created":1,"model":"harness-model","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                    )
                self.wfile.flush()
                if complete:
                    self.close_connection = True
                    return
            # Observe EOF on the actual provider socket, not only a local task flag.
            while not state.release.is_set():
                readable, _, _ = select.select([self.connection], [], [], 0.05)
                if readable:
                    try:
                        disconnected = not self.connection.recv(1)
                    except ConnectionResetError:
                        disconnected = True
                    if disconnected:
                        state.disconnected.set()
                        return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "provider", ["openai", "anthropic", "responses", "gateway_responses"]
)
@pytest.mark.parametrize("send_chunk", [False, True])
@pytest.mark.parametrize("invoke", [False, True])
def test_cancel_closes_provider_connection(
    provider: str, send_chunk: bool, invoke: bool
) -> None:
    with provider_server(
        "responses" if provider == "gateway_responses" else provider, send_chunk
    ) as (url, state):
        signal = CancellationSignal()
        stopped = threading.Event()
        yielded = threading.Event()
        errors: list[BaseException] = []
        llm = LitellmLLM(
            LitellmTransport(
                api_key="local-test-key",
                model_provider="bifrost"
                if provider == "gateway_responses"
                else "openai"
                if provider == "responses"
                else provider,
                custom_config={"bifrost_api_mode": "responses"}
                if provider == "gateway_responses"
                else None,
                model_name="claude-haiku-4-5"
                if provider == "anthropic"
                else "gpt-5-mini"
                if provider == "responses"
                else "harness-model",
                max_input_tokens=4096,
                api_base=url,
                timeout=30,
            )
        )

        def execute() -> None:
            try:
                request = GenerationRequest(messages=[UserMessage(content="test")])
                context = GenerationContext(
                    cancellation=signal, flow=LLMFlow.MODEL_VALIDATION
                )
                if invoke:
                    llm.invoke(request, context)
                else:
                    for event in llm.stream(request, context):
                        if isinstance(event, TextDeltaEvent):
                            yielded.set()
            except AgentCancelled:
                stopped.set()
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=execute, daemon=True)
        worker.start()
        try:
            assert state.started.wait(10), errors
            if send_chunk and not invoke:
                assert yielded.wait(5), errors
            signal.cancel()
            assert stopped.wait(3), errors
            assert state.disconnected.wait(3), "Model request was left running"
            worker.join(timeout=3)
            assert not worker.is_alive()
            assert not errors
            assert state.requests == 1, "Cancellation must not retry inference"
        finally:
            signal.cancel()
            state.release.set()
            worker.join(timeout=3)


@pytest.mark.parametrize("invoke", [False, True])
def test_cancellable_model_completes_normally(invoke: bool) -> None:
    with provider_server("openai", True, complete=True) as (url, state):
        llm = LitellmLLM(
            LitellmTransport(
                api_key="local-test-key",
                model_provider="openai",
                model_name="harness-model",
                max_input_tokens=4096,
                api_base=url,
                timeout=10,
            )
        )
        request = GenerationRequest(messages=[UserMessage(content="test")])
        context = GenerationContext(
            cancellation=CancellationSignal(), flow=LLMFlow.MODEL_VALIDATION
        )
        if invoke:
            text = llm.invoke(request, context).text
        else:
            text = "".join(
                event.text
                for event in llm.stream(request, context)
                if isinstance(event, TextDeltaEvent)
            )
        assert text == "hello"
        assert state.requests == 1


def test_cancel_does_not_interrupt_another_run() -> None:
    with provider_server("openai", True) as (url, blocked):
        signal = CancellationSignal()
        stopped = threading.Event()
        errors: list[BaseException] = []

        def execute() -> None:
            try:
                llm = LitellmLLM(
                    LitellmTransport(
                        api_key="local-test-key",
                        model_provider="openai",
                        model_name="harness-model",
                        max_input_tokens=4096,
                        api_base=url,
                        timeout=10,
                    )
                )
                list(
                    llm.stream(
                        GenerationRequest(messages=[UserMessage(content="test")]),
                        GenerationContext(
                            cancellation=signal, flow=LLMFlow.MODEL_VALIDATION
                        ),
                    )
                )
            except AgentCancelled:
                stopped.set()
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=execute, daemon=True)
        worker.start()
        try:
            assert blocked.started.wait(10), errors
            test_cancellable_model_completes_normally(False)
            assert not stopped.is_set()
            signal.cancel()
            assert stopped.wait(3), errors
            assert blocked.disconnected.wait(3)
            # The shared event loop must remain usable after cancellation.
            test_cancellable_model_completes_normally(True)
            assert not errors
        finally:
            signal.cancel()
            blocked.release.set()
            worker.join(timeout=3)
