"""OpenCode run client for one-shot message execution against a running server."""

import json
import select
import subprocess
import time
from collections.abc import Generator

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


class OpenCodeSessionNotFoundError(RuntimeError):
    """Raised when a requested OpenCode session ID is not available on the server."""


class OpenCodeRunClient:
    """Executes `opencode run --attach` and streams normalized packet events."""

    def __init__(
        self,
        server_url: str,
        session_id: str | None = None,
        cwd: str | None = None,
        timeout: float = OPENCODE_MESSAGE_TIMEOUT,
        keepalive_interval: float = SSE_KEEPALIVE_INTERVAL,
    ) -> None:
        self._server_url = server_url
        self._cwd = cwd
        self._timeout = timeout
        self._keepalive_interval = keepalive_interval
        self._parser = OpenCodeEventParser(session_id=session_id)

    @property
    def session_id(self) -> str | None:
        return self._parser.session_id

    def _build_command(self, message: str) -> list[str]:
        command = [
            "opencode",
            "run",
            "--attach",
            self._server_url,
            "--format",
            "json",
        ]
        if self._parser.session_id:
            command.extend(["--session", self._parser.session_id])
        command.append(message)
        return command

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    def send_message(self, message: str) -> Generator[OpenCodeEvent, None, None]:
        """Send a message and stream normalized events."""
        command = self._build_command(message)
        packet_logger = get_packet_logger()
        packet_logger.log_raw(
            "OPENCODE-RUN-START",
            {
                "server_url": self._server_url,
                "session_id": self._parser.session_id,
                "cwd": self._cwd,
                "command": command,
            },
        )

        process = subprocess.Popen(
            command,
            cwd=self._cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        if process.stdout is None or process.stderr is None:
            self._terminate_process(process)
            yield OpenCodeError(
                opencode_session_id=self._parser.session_id,
                message="Failed to open opencode subprocess pipes",
            )
            return

        start_time = time.monotonic()
        last_event_time = start_time
        stderr_lines: list[str] = []

        stdout_fd = process.stdout.fileno()
        stderr_fd = process.stderr.fileno()
        active_fds = {stdout_fd, stderr_fd}
        fd_to_stream = {
            stdout_fd: process.stdout,
            stderr_fd: process.stderr,
        }

        try:
            while active_fds:
                elapsed = time.monotonic() - start_time
                if elapsed > self._timeout:
                    self._terminate_process(process)
                    yield OpenCodeError(
                        opencode_session_id=self._parser.session_id,
                        code=-1,
                        message=(
                            f"Timeout waiting for OpenCode response after {self._timeout:.1f}s"
                        ),
                    )
                    return

                ready, _, _ = select.select(list(active_fds), [], [], 1.0)
                if not ready:
                    if (time.monotonic() - last_event_time) >= self._keepalive_interval:
                        yield OpenCodeSSEKeepalive()
                        last_event_time = time.monotonic()

                    # Process may have exited while stdout/stderr fds are still open.
                    if process.poll() is not None:
                        for fd in list(active_fds):
                            stream = fd_to_stream[fd]
                            remaining = stream.readline()
                            if not remaining:
                                active_fds.discard(fd)
                            elif fd == stderr_fd:
                                stderr_lines.append(remaining.strip())
                        if process.poll() is not None and not active_fds:
                            break
                    continue

                for fd in ready:
                    stream = fd_to_stream[fd]
                    line = stream.readline()
                    if line == "":
                        active_fds.discard(fd)
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    if fd == stderr_fd:
                        stderr_lines.append(line)
                        continue

                    try:
                        raw_event = json.loads(line)
                    except json.JSONDecodeError:
                        packet_logger.log_raw(
                            "OPENCODE-RUN-PARSE-ERROR",
                            {"line": line[:500]},
                        )
                        continue

                    for event in self._parser.parse_raw_event(raw_event):
                        last_event_time = time.monotonic()
                        yield event
        finally:
            if process.poll() is None:
                self._terminate_process(process)

        return_code = process.returncode
        if return_code is None:
            try:
                return_code = process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._terminate_process(process)
                return_code = process.returncode

        stderr_text = "\n".join(stderr_lines).strip()

        packet_logger.log_raw(
            "OPENCODE-RUN-END",
            {
                "server_url": self._server_url,
                "session_id": self._parser.session_id,
                "cwd": self._cwd,
                "return_code": return_code,
                "stderr_preview": stderr_text[:500] if stderr_text else None,
            },
        )

        if return_code not in (0, None):
            if stderr_text and looks_like_session_not_found(stderr_text):
                raise OpenCodeSessionNotFoundError(stderr_text)
            yield OpenCodeError(
                opencode_session_id=self._parser.session_id,
                code=return_code,
                message=stderr_text or f"OpenCode run exited with code {return_code}",
            )
            return

        if not self._parser.saw_prompt_response:
            yield OpenCodePromptResponse(
                opencode_session_id=self._parser.session_id,
                stop_reason="completed",
            )
