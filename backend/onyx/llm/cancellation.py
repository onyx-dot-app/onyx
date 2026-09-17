"""Cancellation signals, execution scopes, and interruptible provider streaming."""

import socket
import threading
from collections.abc import Callable, Generator, Iterator
from concurrent.futures import Future
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

import httpx
from httpcore import NetworkStream
from pydantic import JsonValue
from typing_extensions import TypedDict

from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

logger = setup_logger()

_CONNECTION_ESTABLISHED = {
    "connection.connect_tcp.complete",
    "connection.connect_unix_socket.complete",
}


class AgentCancelled(BaseException):
    """Cancellation control flow bypasses ordinary model/tool error recovery."""


class CancellationSignal:
    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: set[Callable[[], None]] = set()
        self._operation_listeners: set[Callable[[Future[None]], None]] = set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise AgentCancelled()

    def cancel(self) -> None:
        with self._lock:
            if self.cancelled:
                return
            self._cancelled.set()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception("Agent cancellation callback failed")

    @contextmanager
    def on_cancel(self, callback: Callable[[], None]) -> Iterator[None]:
        def notify() -> None:
            return callback()

        with self._lock:
            cancelled = self.cancelled
            if not cancelled:
                self._callbacks.add(notify)
        try:
            if cancelled:
                callback()
            yield
        finally:
            with self._lock:
                self._callbacks.discard(notify)

    def track_operation(self, completion: Future[None]) -> None:
        with self._lock:
            listeners = tuple(self._operation_listeners)
        for listener in listeners:
            listener(completion)

    @contextmanager
    def on_operation(self, listener: Callable[[Future[None]], None]) -> Iterator[None]:
        """Observe provider work until actual cleanup finishes, including after timeout."""

        def notify(completion: Future[None]) -> None:
            listener(completion)

        with self._lock:
            self._operation_listeners.add(notify)
        try:
            yield
        finally:
            with self._lock:
                self._operation_listeners.discard(notify)


_current_signal: ContextVar[CancellationSignal | None] = ContextVar(
    "agent_cancellation", default=None
)


def current_cancellation() -> CancellationSignal | None:
    return _current_signal.get()


def check_cancelled() -> None:
    signal = current_cancellation()
    if signal is not None:
        signal.check()


@contextmanager
def cancellation_scope(signal: CancellationSignal) -> Iterator[None]:
    token = _current_signal.set(signal)
    try:
        yield
    finally:
        _current_signal.reset(token)


if TYPE_CHECKING:
    from litellm.types.utils import ModelResponseStream
    from openai import AzureOpenAI, OpenAI


@contextmanager
def cancellation_deadline(
    seconds: float, callback: Callable[[], None]
) -> Iterator[None]:
    stopped = threading.Event()

    def expire() -> None:
        if not stopped.wait(seconds):
            callback()

    watcher = start_thread_with_context(expire, name="llm-deadline", daemon=True)
    try:
        yield
    finally:
        stopped.set()
        watcher.join(timeout=1)


class _ConnectionTrace(TypedDict):
    return_value: NetworkStream


class CancellableStream(Iterator["ModelResponseStream"]):
    """Own a synchronous provider connection and interrupt its reads on cancellation."""

    def __init__(
        self,
        kwargs: dict[str, JsonValue],
        signal: CancellationSignal,
        *,
        timeout: float,
    ) -> None:
        from litellm import CustomStreamWrapper, HTTPHandler
        from openai import OpenAI

        from onyx.llm.litellm_singleton import litellm

        self._signal = signal
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self._closed = False
        self._response: CustomStreamWrapper | None = None
        self._completion: Future[None] = Future()
        self._completion.set_running_or_notify_cancel()
        self._resources = ExitStack()
        try:
            signal.track_operation(self._completion)
            signal.check()
            self._resources.enter_context(signal.on_cancel(self._abort))
            handler = HTTPHandler(timeout=timeout)
            self._resources.callback(handler.close)
            handler.client.event_hooks["request"].append(self._prepare_request)
            model = cast(str, kwargs["model"])
            provider = kwargs.get("custom_llm_provider") or model.partition("/")[0]
            if provider == "openai" and "responses/" not in model:
                # LiteLLM's OpenAI chat adapter accepts the SDK client, not HTTPHandler.
                client = OpenAI(
                    api_key=cast(str | None, kwargs.get("api_key")),
                    base_url=cast(str | None, kwargs.get("base_url")),
                    http_client=handler.client,
                    max_retries=0,
                )
            elif provider == "azure" and "responses/" not in model:
                client = _azure_client(kwargs, handler.client, timeout)
            else:
                client = handler
            response = litellm.completion(**kwargs, client=client)
            if not isinstance(response, CustomStreamWrapper):
                raise TypeError("Expected a streaming model response")
            self._response = response
            signal.check()
        except BaseException:
            self.close()
            signal.check()
            raise

    def _prepare_request(self, request: httpx.Request) -> None:
        self._signal.check()
        request.extensions["trace"] = self._trace_connection

    def _trace_connection(self, name: str, info: _ConnectionTrace) -> None:
        if name not in _CONNECTION_ESTABLISHED:
            return
        # HTTPX's trace extension exposes the raw socket before TLS takes ownership.
        # https://www.python-httpx.org/advanced/extensions/#trace
        connection = cast(socket.socket, info["return_value"].get_extra_info("socket"))
        duplicate = connection.dup()
        with self._lock:
            self._sockets.append(duplicate)
            if self._signal.cancelled:
                self._shutdown(duplicate)
        self._signal.check()

    @staticmethod
    def _shutdown(connection: socket.socket) -> None:
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            logger.debug("Provider connection already closed during cancellation")

    def _abort(self) -> None:
        with self._lock:
            for connection in self._sockets:
                self._shutdown(connection)

    def __next__(self) -> "ModelResponseStream":
        if self._closed or self._response is None:
            raise StopIteration
        try:
            self._signal.check()
            chunk = next(self._response)
            self._signal.check()
            return chunk
        except BaseException:
            self.close()
            self._signal.check()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._resources.close()
        except Exception:
            logger.exception("Provider stream cleanup failed")
        finally:
            with self._lock:
                for connection in self._sockets:
                    connection.close()
                self._sockets.clear()
            self._completion.set_result(None)


def _azure_client(
    kwargs: dict[str, JsonValue], http_client: httpx.Client, timeout: float
) -> "OpenAI | AzureOpenAI":
    from litellm.llms.azure.common_utils import BaseAzureLLM
    from litellm.secret_managers.main import get_secret_str
    from openai import AzureOpenAI, OpenAI

    from onyx.llm.litellm_singleton import litellm

    api_base = cast(str | None, kwargs.get("base_url") or kwargs.get("api_base"))
    api_base = api_base or litellm.api_base or get_secret_str("AZURE_API_BASE")
    api_version = cast(str | None, kwargs.get("api_version"))
    api_version = (
        api_version or litellm.api_version or get_secret_str("AZURE_API_VERSION")
    )
    api_key = cast(str | None, kwargs.get("api_key"))
    api_key = (
        api_key
        or litellm.api_key
        or litellm.azure_key
        or get_secret_str("AZURE_OPENAI_API_KEY")
        or get_secret_str("AZURE_API_KEY")
    )
    params = dict(kwargs)
    params["azure_ad_token"] = params.get("azure_ad_token") or get_secret_str(
        "AZURE_AD_TOKEN"
    )
    params.update(max_retries=0, timeout=timeout)
    configuration = BaseAzureLLM().initialize_azure_sdk_client(
        litellm_params=params,
        api_key=api_key,
        api_base=api_base,
        model_name=cast(str, kwargs["model"]),
        api_version=api_version,
        is_async=False,
    )
    configuration["http_client"] = http_client
    if BaseAzureLLM._is_azure_v1_api_version(api_version):
        return OpenAI(
            api_key=configuration.get("api_key")
            or configuration.get("azure_ad_token_provider")
            or configuration.get("azure_ad_token"),
            base_url=f"{api_base}/openai/v1/",
            http_client=http_client,
            max_retries=0,
            timeout=timeout,
        )
    return AzureOpenAI(**configuration)


_P = ParamSpec("_P")

_T = TypeVar("_T")


def isolated_context(
    generate: Callable[_P, Generator[_T, None, None]],
) -> Callable[_P, Generator[_T, None, None]]:
    """Keep generator context variables isolated across next and close operations."""

    @wraps(generate)
    def start(*args: _P.args, **kwargs: _P.kwargs) -> Generator[_T, None, None]:
        execution = copy_context()
        source = execution.run(generate, *args, **kwargs)

        def iterate() -> Generator[_T, None, None]:
            try:
                while True:
                    try:
                        value = execution.run(source.__next__)
                    except StopIteration:
                        return
                    yield value
            finally:
                execution.run(source.close)

        return iterate()

    return start
