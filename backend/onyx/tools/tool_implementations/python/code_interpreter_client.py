import json
from collections.abc import Generator
from typing import Literal
from typing import TypedDict
from typing import Union

import requests
from pydantic import BaseModel

from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
                "Streaming endpoint not available, " "falling back to batch execution"
            )
            response.close()
            yield from self._batch_as_stream(code, stdin, timeout_ms, files)
            return

        response.raise_for_status()
        yield from self._parse_sse(response)

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
                        logger.warning(f"Unknown SSE event type: {event_type}")
                event_type = None
                data_lines = []
            elif line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())

        if event_type is not None or data_lines:
            logger.warning(
                f"SSE stream ended with incomplete event: "
                f"event_type={event_type}, data_lines={data_lines}"
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
