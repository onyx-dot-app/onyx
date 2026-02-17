"""Run OpenCode client commands inside a sandbox pod via Kubernetes exec."""

import json
import time
from collections.abc import Generator

from kubernetes import client  # type: ignore
from kubernetes.stream import stream as k8s_stream  # type: ignore
from kubernetes.stream.ws_client import WSClient  # type: ignore

from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import OPENCODE_MESSAGE_TIMEOUT
from onyx.server.features.build.configs import SSE_KEEPALIVE_INTERVAL
from onyx.server.features.build.sandbox.opencode.events import OpenCodeError
from onyx.server.features.build.sandbox.opencode.events import OpenCodeEvent
from onyx.server.features.build.sandbox.opencode.events import OpenCodePromptResponse
from onyx.server.features.build.sandbox.opencode.events import OpenCodeSSEKeepalive
from onyx.server.features.build.sandbox.opencode.parser import (
    looks_like_session_not_found,
)
from onyx.server.features.build.sandbox.opencode.parser import OpenCodeEventParser
from onyx.server.features.build.sandbox.opencode.run_client import (
    OpenCodeSessionNotFoundError,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

STATUS_CHANNEL = 3


def _drain_lines(buffer: str) -> tuple[list[str], str]:
    """Split buffered stream data into complete stripped lines."""
    if "\n" not in buffer:
        return [], buffer

    parts = buffer.split("\n")
    lines = [line.strip() for line in parts[:-1] if line.strip()]
    return lines, parts[-1]


def _parse_exec_exit_code(status_payload: str) -> int | None:
    """Parse Kubernetes exec status channel payload for exit code."""
    if not status_payload:
        return None

    payload = status_payload.strip().splitlines()[-1]

    try:
        status_obj = json.loads(payload)
    except json.JSONDecodeError:
        return None

    causes = status_obj.get("details", {}).get("causes", [])
    if not isinstance(causes, list):
        return None

    for cause in causes:
        if not isinstance(cause, dict):
            continue
        if cause.get("reason") == "ExitCode":
            message = cause.get("message")
            if isinstance(message, str) and message.isdigit():
                return int(message)
    return None


class OpenCodeExecClient:
    """Run `opencode run --attach` in a pod and stream normalized events."""

    def __init__(
        self,
        core_api: client.CoreV1Api,
        pod_name: str,
        namespace: str,
        container: str = "sandbox",
        timeout: float = OPENCODE_MESSAGE_TIMEOUT,
        keepalive_interval: float = SSE_KEEPALIVE_INTERVAL,
    ) -> None:
        self._core_api = core_api
        self._pod_name = pod_name
        self._namespace = namespace
        self._container = container
        self._timeout = timeout
        self._keepalive_interval = keepalive_interval

    @staticmethod
    def _read_channel(ws_client: WSClient, channel: int) -> str:
        try:
            return ws_client.read_channel(channel)
        except Exception:
            return ""

    def send_message(
        self,
        server_url: str,
        message: str,
        cwd: str,
        session_id: str | None = None,
    ) -> Generator[OpenCodeEvent, None, None]:
        """Send one user message via pod exec and stream normalized OpenCode events."""
        command = [
            "/bin/sh",
            "-c",
            'cd "$1" && shift && exec "$@"',
            "sh",
            cwd,
            "opencode",
            "run",
            "--attach",
            server_url,
            "--format",
            "json",
            *(["--session", session_id] if session_id else []),
            message,
        ]

        packet_logger = get_packet_logger()
        packet_logger.log_raw(
            "OPENCODE-K8S-RUN-START",
            {
                "pod_name": self._pod_name,
                "namespace": self._namespace,
                "container": self._container,
                "cwd": cwd,
                "server_url": server_url,
                "session_id": session_id,
                "command": command,
            },
        )

        ws_client: WSClient | None = None
        parser = OpenCodeEventParser(session_id=session_id)
        stdout_buffer = ""
        stderr_buffer = ""
        stderr_lines: list[str] = []
        status_payload = ""
        start_time = time.monotonic()
        last_event_time = start_time

        try:
            ws_client = k8s_stream(
                self._core_api.connect_get_namespaced_pod_exec,
                name=self._pod_name,
                namespace=self._namespace,
                container=self._container,
                command=command,
                stdin=False,
                stdout=True,
                stderr=True,
                tty=False,
                _preload_content=False,
                _request_timeout=int(self._timeout) + 30,
            )

            while True:
                elapsed = time.monotonic() - start_time
                if elapsed > self._timeout:
                    yield OpenCodeError(
                        opencode_session_id=parser.session_id,
                        code=-1,
                        message=(
                            f"Timeout waiting for OpenCode response after {self._timeout:.1f}s"
                        ),
                    )
                    return

                if ws_client.is_open():
                    ws_client.update(timeout=0.5)

                try:
                    stdout_chunk = ws_client.read_stdout(timeout=0.1)
                except Exception:
                    stdout_chunk = ""
                try:
                    stderr_chunk = ws_client.read_stderr(timeout=0.1)
                except Exception:
                    stderr_chunk = ""
                status_chunk = self._read_channel(ws_client, STATUS_CHANNEL)
                if status_chunk:
                    status_payload += status_chunk

                if stdout_chunk:
                    stdout_buffer += stdout_chunk
                    lines, stdout_buffer = _drain_lines(stdout_buffer)
                    for line in lines:
                        try:
                            raw_event = json.loads(line)
                        except json.JSONDecodeError:
                            packet_logger.log_raw(
                                "OPENCODE-K8S-RUN-PARSE-ERROR",
                                {"line": line[:500]},
                            )
                            continue

                        for event in parser.parse_raw_event(raw_event):
                            last_event_time = time.monotonic()
                            yield event

                if stderr_chunk:
                    stderr_buffer += stderr_chunk
                    lines, stderr_buffer = _drain_lines(stderr_buffer)
                    stderr_lines.extend(lines)

                if (
                    not stdout_chunk
                    and not stderr_chunk
                    and (time.monotonic() - last_event_time) >= self._keepalive_interval
                ):
                    yield OpenCodeSSEKeepalive()
                    last_event_time = time.monotonic()

                if not ws_client.is_open() and not stdout_chunk and not stderr_chunk:
                    break

            # Flush any trailing partial lines
            trailing_stdout = stdout_buffer.strip()
            if trailing_stdout:
                try:
                    raw_event = json.loads(trailing_stdout)
                    for event in parser.parse_raw_event(raw_event):
                        yield event
                except json.JSONDecodeError:
                    packet_logger.log_raw(
                        "OPENCODE-K8S-RUN-PARSE-ERROR",
                        {"line": trailing_stdout[:500]},
                    )

            trailing_stderr = stderr_buffer.strip()
            if trailing_stderr:
                stderr_lines.append(trailing_stderr)

            stderr_text = "\n".join(stderr_lines).strip()
            exit_code = _parse_exec_exit_code(status_payload)

            packet_logger.log_raw(
                "OPENCODE-K8S-RUN-END",
                {
                    "pod_name": self._pod_name,
                    "namespace": self._namespace,
                    "container": self._container,
                    "cwd": cwd,
                    "server_url": server_url,
                    "session_id": parser.session_id,
                    "stderr_preview": stderr_text[:500] if stderr_text else None,
                    "exit_code": exit_code,
                },
            )

            if stderr_text and looks_like_session_not_found(stderr_text):
                raise OpenCodeSessionNotFoundError(stderr_text)

            if (exit_code not in (None, 0)) or stderr_text:
                yield OpenCodeError(
                    opencode_session_id=parser.session_id,
                    code=exit_code,
                    message=stderr_text
                    or f"OpenCode run failed with exit code {exit_code}",
                )
                return

            if not parser.saw_prompt_response:
                yield OpenCodePromptResponse(
                    opencode_session_id=parser.session_id,
                    stop_reason="completed",
                )
        finally:
            if ws_client is not None:
                try:
                    ws_client.close()
                except Exception as e:
                    logger.debug(f"Failed to close OpenCode exec websocket: {e}")
