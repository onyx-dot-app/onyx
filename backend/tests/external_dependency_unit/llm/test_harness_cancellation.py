"""Exercise real LiteLLM HTTP connections without external provider credentials."""

import datetime as dt
import ipaddress
import json
import select
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import GenerationRequest, TextDeltaEvent, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.flows import LLMFlow


class ProviderState:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.disconnected = threading.Event()
        self.release = threading.Event()
        self.requests = 0
        self.path = ""
        self.headers: dict[str, str] = {}


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
    provider: str,
    send_chunk: bool,
    complete: bool = False,
    tls: ssl.SSLContext | None = None,
) -> Iterator[tuple[str, ProviderState]]:
    state = ProviderState()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            state.requests += 1
            state.path = self.path
            state.headers = dict(self.headers)
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
            state.started.set()
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
    if tls is not None:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        scheme = "https" if tls is not None else "http"
        yield f"{scheme}://127.0.0.1:{server.server_port}", state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture(params=[False, True], ids=["http", "https"])
def provider_tls(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ssl.SSLContext | None:
    if not request.param:
        return None
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "provider.crt"
    key_path = tmp_path / "provider.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("SSL_CERT_FILE", str(cert_path))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context


@pytest.mark.parametrize(
    "provider", ["openai", "anthropic", "responses", "gateway_responses", "azure"]
)
@pytest.mark.parametrize("send_chunk", [False, True])
@pytest.mark.parametrize("invoke", [False, True])
def test_cancel_closes_provider_connection(
    provider: str, send_chunk: bool, invoke: bool, provider_tls: ssl.SSLContext | None
) -> None:
    with provider_server(
        "responses" if provider == "gateway_responses" else provider,
        send_chunk,
        tls=provider_tls,
    ) as (url, state):
        signal = CancellationSignal()
        stopped = threading.Event()
        yielded = threading.Event()
        errors: list[BaseException] = []
        llm = LitellmLLM(
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
            api_key="local-test-key",
            model_provider="openai",
            model_name="harness-model",
            max_input_tokens=4096,
            api_base=url,
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
                    api_key="local-test-key",
                    model_provider="openai",
                    model_name="harness-model",
                    max_input_tokens=4096,
                    api_base=url,
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


@pytest.mark.parametrize("api_version", ["2024-02-01", "v1"])
@pytest.mark.parametrize("ad_token", [False, True])
def test_azure_preserves_authentication_and_endpoint(
    api_version: str, ad_token: bool
) -> None:
    with provider_server("azure", send_chunk=True, complete=True) as (url, state):
        client = LitellmLLM(
            api_key=None if ad_token else "azure-test-key",
            model_provider="azure",
            model_name="harness-model",
            api_base=url,
            api_version=api_version,
            custom_config={"AZURE_AD_TOKEN": "azure-test-token"} if ad_token else None,
            max_input_tokens=4096,
        )
        result = client.invoke(
            GenerationRequest(messages=[UserMessage(content="test")]),
            GenerationContext(flow=LLMFlow.MODEL_VALIDATION),
        )
    assert result.text == "hello"
    if api_version == "v1":
        assert state.path == "/openai/v1/chat/completions"
        assert state.headers["Authorization"] == (
            "Bearer azure-test-token" if ad_token else "Bearer azure-test-key"
        )
    else:
        assert (
            state.path
            == "/openai/deployments/harness-model/chat/completions?api-version=2024-02-01"
        )
        if ad_token:
            assert state.headers["Authorization"] == "Bearer azure-test-token"
        else:
            assert state.headers["api-key"] == "azure-test-key"
