from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from collections.abc import Generator
from functools import wraps
from typing import Any
from typing import Concatenate
from typing import Literal
from typing import ParamSpec
from typing import TypedDict
from typing import TypeVar
from typing import Union

import requests
from pydantic import BaseModel

from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
from onyx.utils.logger import setup_logger

logger = setup_logger()

_HEALTH_CACHE_TTL_SECONDS = 30
_DEFAULT_SERVER_VERSION = "0.0.0"
_health_cache: dict[str, tuple[float, "HealthResponse"]] = {}


class CodeInterpreterVersionError(RuntimeError):
    """Raised when the connected Code Interpreter is older than the called
    method requires."""

    def __init__(self, method_name: str, server_version: str, required: str) -> None:
        self.method_name = method_name
        self.server_version = server_version
        self.required = required
        super().__init__(
            f"Code Interpreter server {server_version} does not support "
            f"'{method_name}' (requires >= {required})"
        )


_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-+].*)?$")


def _parse_version(version: str) -> tuple[int, int, int]:
    """Parse ``MAJOR.MINOR.PATCH``; suffixes are ignored. Malformed input
    falls back to ``(0, 0, 0)`` so a misreporting server is treated as
    ancient rather than crashing the gate."""
    clean = re.sub(r"[-+].*$", "", version.lstrip("v"))
    parts = clean.split(".")
    try:
        return (
            int(parts[0]),
            int(parts[1]) if len(parts) > 1 else 0,
            int(parts[2]) if len(parts) > 2 else 0,
        )
    except ValueError:
        return (0, 0, 0)


def _is_version_gte(actual: str, required: str) -> bool:
    return _parse_version(actual) >= _parse_version(required)


_P = ParamSpec("_P")
_R = TypeVar("_R")

_MIN_VERSION_ATTR = "__ci_min_version__"


def requires(
    min_version: str,
) -> Callable[
    [Callable[Concatenate["CodeInterpreterClient", _P], _R]],
    Callable[Concatenate["CodeInterpreterClient", _P], _R],
]:
    """Gate a method on a minimum server version. Raises
    ``CodeInterpreterVersionError`` at call time, and records the minimum on
    the wrapper so ``client.supports(method)`` can introspect it."""
    if not _VERSION_RE.match(min_version):
        raise ValueError(
            f"@requires expects a MAJOR.MINOR.PATCH version, got {min_version!r}"
        )

    def decorator(
        func: Callable[Concatenate["CodeInterpreterClient", _P], _R],
    ) -> Callable[Concatenate["CodeInterpreterClient", _P], _R]:
        # ``Callable`` doesn't promise a ``__name__``; ours always do.
        method_name = getattr(func, "__name__", "<unknown>")

        @wraps(func)
        def wrapper(
            self: "CodeInterpreterClient", *args: _P.args, **kwargs: _P.kwargs
        ) -> _R:
            self._require(min_version, method_name=method_name)
            return func(self, *args, **kwargs)

        # Bound-method attribute lookup falls through to the underlying
        # function, so ``client.foo.__ci_min_version__`` works.
        setattr(wrapper, _MIN_VERSION_ATTR, min_version)
        return wrapper

    return decorator


def _min_version_for(method: Callable[..., object]) -> str:
    """Min server version recorded on a method, or ``"0.0.0"`` (always
    supported) when the method isn't ``@requires``-decorated."""
    return getattr(method, _MIN_VERSION_ATTR, _DEFAULT_SERVER_VERSION)


class HealthResponse(BaseModel):
    """Result of a Code Interpreter health check"""

    healthy: bool
    version: str = _DEFAULT_SERVER_VERSION


class FileInput(TypedDict):
    """Input file to be staged in execution workspace"""

    path: str
    file_id: str


class WorkspaceFile(BaseModel):
    """File in execution workspace"""

    path: str
    kind: Literal["file", "directory"]
    file_id: str | None = None


class ExecuteResponse(BaseModel):
    """Response from code execution"""

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    files: list[WorkspaceFile]


class StreamOutputEvent(BaseModel):
    """SSE 'output' event: a chunk of stdout or stderr"""

    stream: Literal["stdout", "stderr"]
    data: str


class StreamResultEvent(BaseModel):
    """SSE 'result' event: final execution result"""

    exit_code: int | None
    timed_out: bool
    duration_ms: int
    files: list[WorkspaceFile]


class StreamErrorEvent(BaseModel):
    """SSE 'error' event: execution-level error"""

    message: str


StreamEvent = Union[StreamOutputEvent, StreamResultEvent, StreamErrorEvent]


class CreateSessionResponse(BaseModel):
    """Response from creating a long-lived execution session"""

    session_id: str
    expires_at: float


class BashExecResponse(BaseModel):
    """Response from executing a bash command in a session"""

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    duration_ms: int


_SSE_EVENT_MAP: dict[
    str, type[StreamOutputEvent | StreamResultEvent | StreamErrorEvent]
] = {
    "output": StreamOutputEvent,
    "result": StreamResultEvent,
    "error": StreamErrorEvent,
}


class CodeInterpreterClient:
    """Client for Code Interpreter service"""

    def __init__(self, base_url: str | None = CODE_INTERPRETER_BASE_URL):
        if not base_url:
            raise ValueError("CODE_INTERPRETER_BASE_URL not configured")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._closed = False

    def __enter__(self) -> CodeInterpreterClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self.session.close()
        self._closed = True

    def _build_payload(
        self,
        code: str,
        stdin: str | None,
        timeout_ms: int,
        files: list[FileInput] | None,
    ) -> dict:
        payload: dict = {
            "code": code,
            "timeout_ms": timeout_ms,
        }
        if stdin is not None:
            payload["stdin"] = stdin
        if files:
            payload["files"] = files
        return payload

    def health(self, use_cache: bool = False) -> HealthResponse:
        """Check if the Code Interpreter service is healthy

        Returns a ``HealthResponse`` containing both the health status and the
        server version (defaults to ``"0.0.0"`` when the server is unhealthy
        or the response does not include a version field — e.g. older
        code-interpreter releases that pre-date version reporting).

        Args:
            use_cache: When True, return a cached result if available and
                       within the TTL window. The cache is always populated
                       after a live request regardless of this flag.
        """
        if use_cache:
            cached = _health_cache.get(self.base_url)
            if cached is not None:
                cached_at, cached_result = cached
                if time.monotonic() - cached_at < _HEALTH_CACHE_TTL_SECONDS:
                    return cached_result

        url = f"{self.base_url}/health"
        try:
            response = self.session.get(url, timeout=5)
            response.raise_for_status()
            body = response.json()
            healthy = body.get("status") == "ok"
            version = body.get("version") or _DEFAULT_SERVER_VERSION
            result = HealthResponse(healthy=healthy, version=version)
        except Exception as e:
            logger.warning("Exception caught when checking health, e=%s", e)
            result = HealthResponse(healthy=False, version=_DEFAULT_SERVER_VERSION)

        _health_cache[self.base_url] = (time.monotonic(), result)
        return result

    def supports(self, *methods: Callable[..., object]) -> bool:
        """True iff the server version satisfies every listed method's
        ``@requires`` minimum (undecorated methods default to ``"0.0.0"``).
        """
        if not methods:
            raise ValueError("supports() requires at least one method")

        server_version = self.health(use_cache=True).version
        return all(
            _is_version_gte(server_version, _min_version_for(m)) for m in methods
        )

    def _require(self, min_version: str, method_name: str) -> None:
        """Raise ``CodeInterpreterVersionError`` if server is older than
        *min_version*."""
        server_version = self.health(use_cache=True).version
        if not _is_version_gte(server_version, min_version):
            raise CodeInterpreterVersionError(
                method_name=method_name,
                server_version=server_version,
                required=min_version,
            )

    def execute(
        self,
        code: str,
        stdin: str | None = None,
        timeout_ms: int = 30000,
        files: list[FileInput] | None = None,
    ) -> ExecuteResponse:
        """Execute Python code (batch)"""
        url = f"{self.base_url}/v1/execute"
        payload = self._build_payload(code, stdin, timeout_ms, files)

        response = self.session.post(url, json=payload, timeout=timeout_ms / 1000 + 10)
        response.raise_for_status()

        return ExecuteResponse(**response.json())

    def execute_streaming(
        self,
        code: str,
        stdin: str | None = None,
        timeout_ms: int = 30000,
        files: list[FileInput] | None = None,
    ) -> Generator[StreamEvent, None, None]:
        """Execute Python code with streaming SSE output.

        Yields StreamEvent objects (StreamOutputEvent, StreamResultEvent,
        StreamErrorEvent) as execution progresses. Falls back to batch
        execution if the streaming endpoint is not available (older
        code-interpreter versions).
        """
        url = f"{self.base_url}/v1/execute/stream"
        payload = self._build_payload(code, stdin, timeout_ms, files)

        response = self.session.post(
            url,
            json=payload,
            stream=True,
            timeout=timeout_ms / 1000 + 10,
        )

        if response.status_code == 404:
            logger.info(
                "Streaming endpoint not available, falling back to batch execution"
            )
            response.close()
            yield from self._batch_as_stream(code, stdin, timeout_ms, files)
            return

        try:
            response.raise_for_status()
            yield from self._parse_sse(response)
        finally:
            response.close()

    def _parse_sse(
        self, response: requests.Response
    ) -> Generator[StreamEvent, None, None]:
        """Parse SSE streaming response into StreamEvent objects.

        Expected format per event:
            event: <type>
            data: <json>
            <blank line>
        """
        event_type: str | None = None
        data_lines: list[str] = []

        for line in response.iter_lines(decode_unicode=True):
            if line is None:
                continue

            if line == "":
                # Blank line marks end of an SSE event
                if event_type is not None and data_lines:
                    data = "\n".join(data_lines)
                    model_cls = _SSE_EVENT_MAP.get(event_type)
                    if model_cls is not None:
                        yield model_cls(**json.loads(data))
                    else:
                        logger.warning("Unknown SSE event type: %s", event_type)
                event_type = None
                data_lines = []
            elif line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())

        if event_type is not None or data_lines:
            logger.warning(
                "SSE stream ended with incomplete event: event_type=%s, data_lines=%s",
                event_type,
                data_lines,
            )

    def _batch_as_stream(
        self,
        code: str,
        stdin: str | None,
        timeout_ms: int,
        files: list[FileInput] | None,
    ) -> Generator[StreamEvent, None, None]:
        """Execute via batch endpoint and yield results as stream events."""
        result = self.execute(code, stdin, timeout_ms, files)

        if result.stdout:
            yield StreamOutputEvent(stream="stdout", data=result.stdout)
        if result.stderr:
            yield StreamOutputEvent(stream="stderr", data=result.stderr)
        yield StreamResultEvent(
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            duration_ms=result.duration_ms,
            files=result.files,
        )

    @requires("0.4.0")
    def create_session(
        self,
        ttl_seconds: int = 15 * 60,
        files: list[FileInput] | None = None,
    ) -> CreateSessionResponse:
        """Create a long-lived code-executor session with the given TTL.

        The pod is guaranteed to be torn down at or before the TTL expires,
        even if the API service crashes and restarts.
        """
        url = f"{self.base_url}/v1/sessions"
        payload: dict[str, Any] = {"ttl_seconds": ttl_seconds}
        if files:
            payload["files"] = files

        response = self.session.post(url, json=payload, timeout=30)
        response.raise_for_status()

        return CreateSessionResponse(**response.json())

    @requires("0.4.0")
    def delete_session(self, session_id: str) -> None:
        """Tear down a session pod by ID."""
        url = f"{self.base_url}/v1/sessions/{session_id}"

        response = self.session.delete(url, timeout=30)
        response.raise_for_status()

    @requires("0.4.0")
    def execute_bash_in_session(
        self,
        session_id: str,
        cmd: str,
        timeout_ms: int = 30000,
    ) -> BashExecResponse:
        """Run a bash command inside an existing session.

        The session pod has no network access (enforced at session creation),
        and that restriction continues to apply for every command run via
        this route.
        """
        url = f"{self.base_url}/v1/sessions/{session_id}/bash"
        payload = {"cmd": cmd, "timeout_ms": timeout_ms}

        response = self.session.post(url, json=payload, timeout=timeout_ms / 1000 + 10)
        response.raise_for_status()

        return BashExecResponse(**response.json())

    def upload_file(self, file_content: bytes, filename: str) -> str:
        """Upload file to Code Interpreter and return file_id"""
        url = f"{self.base_url}/v1/files"

        files = {"file": (filename, file_content)}
        response = self.session.post(url, files=files, timeout=30)
        response.raise_for_status()

        return response.json()["file_id"]

    def download_file(self, file_id: str) -> bytes:
        """Download file from Code Interpreter"""
        url = f"{self.base_url}/v1/files/{file_id}"

        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        return response.content

    def delete_file(self, file_id: str) -> None:
        """Delete file from Code Interpreter"""
        url = f"{self.base_url}/v1/files/{file_id}"

        response = self.session.delete(url, timeout=10)
        response.raise_for_status()
