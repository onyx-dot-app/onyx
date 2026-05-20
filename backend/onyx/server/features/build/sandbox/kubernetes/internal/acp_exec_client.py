"""ACP client that communicates via kubectl exec into the sandbox pod.

This client runs ``opencode acp`` directly in the sandbox pod via kubernetes
exec, using stdin/stdout for JSON-RPC communication. The protocol code lives
on :class:`ACPExecClientBase`; this subclass owns the kubernetes-exec
transport.

Each message creates an ephemeral client (start → resume_or_create_session →
send_message → stop) to prevent concurrent processes from corrupting
opencode's flat-file session storage.
"""

from __future__ import annotations

import json
import shlex
from typing import Any
from typing import ClassVar

from kubernetes import client
from kubernetes import config
from kubernetes.stream import stream as k8s_stream
from kubernetes.stream.ws_client import WSClient

from onyx.server.features.build.sandbox.acp.base import ACPExecClientBase
from onyx.utils.logger import setup_logger

logger = setup_logger()


DEFAULT_CLIENT_INFO = {
    "name": "onyx-sandbox-k8s-exec",
    "title": "Onyx Sandbox Agent Client (K8s Exec)",
    "version": "1.0.0",
}


class ACPExecClient(ACPExecClientBase):
    """ACP client that communicates via the kubernetes exec WebSocket."""

    transport_name: ClassVar[str] = "k8s"

    def __init__(
        self,
        pod_name: str,
        namespace: str,
        container: str = "sandbox",
        client_info: dict[str, Any] | None = None,
        client_capabilities: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            client_info=client_info or DEFAULT_CLIENT_INFO,
            client_capabilities=client_capabilities,
        )
        self._pod_name = pod_name
        self._namespace = namespace
        self._container = container
        self._ws_client: WSClient | None = None
        self._k8s_client: client.CoreV1Api | None = None

    def _get_k8s_client(self) -> client.CoreV1Api:
        if self._k8s_client is None:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            self._k8s_client = client.CoreV1Api()
        return self._k8s_client

    # ------------------------------------------------------------------
    # Transport hooks
    # ------------------------------------------------------------------

    def _log_target(self) -> str:
        return f"pod={self._pod_name}"

    def _open_transport(self, cwd: str) -> None:
        k8s = self._get_k8s_client()

        # Set XDG_DATA_HOME so opencode stores session data on the shared
        # workspace volume rather than the container-local
        # ~/.local/share/ filesystem.
        data_dir = shlex.quote(f"{cwd}/.opencode-data")
        safe_cwd = shlex.quote(cwd)
        exec_command = [
            "/bin/sh",
            "-c",
            f"XDG_DATA_HOME={data_dir} exec opencode acp --cwd {safe_cwd}",
        ]

        self._ws_client = k8s_stream(
            k8s.connect_get_namespaced_pod_exec,
            name=self._pod_name,
            namespace=self._namespace,
            container=self._container,
            command=exec_command,
            stdin=True,
            stdout=True,
            stderr=True,
            tty=False,
            _preload_content=False,
            _request_timeout=900,  # 15 min — long-running session
        )

    def _close_transport(self) -> None:
        if self._ws_client is not None:
            try:
                self._ws_client.close()
            except Exception:
                pass
            self._ws_client = None

    def _is_transport_open(self) -> bool:
        return self._ws_client is not None and self._ws_client.is_open()

    def _write_line(self, line: str) -> None:
        ws = self._ws_client
        if ws is None or not ws.is_open():
            raise RuntimeError("Exec session not open")
        ws.write_stdin(line)

    def _read_responses_loop(self) -> None:
        buffer = ""

        while not self._stop_reader.is_set():
            ws = self._ws_client
            if ws is None:
                break

            try:
                if ws.is_open():
                    ws.update(timeout=0.1)

                    stderr_data = ws.read_stderr(timeout=0.01)
                    if stderr_data:
                        logger.warning(
                            "%s stderr %s: %s",
                            self._log_prefix,
                            self._log_target(),
                            stderr_data.strip()[:500],
                        )

                    data = ws.read_stdout(timeout=0.1)
                    if data:
                        buffer += data
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                message = json.loads(line)
                            except json.JSONDecodeError:
                                logger.warning(
                                    "%s Invalid JSON from agent: %s",
                                    self._log_prefix,
                                    line[:100],
                                )
                                continue
                            self._enqueue_message(message)
                else:
                    logger.warning(
                        "%s WebSocket closed: %s",
                        self._log_prefix,
                        self._log_target(),
                    )
                    break

            except Exception as e:
                if not self._stop_reader.is_set():
                    logger.warning(
                        "%s Reader error: %s, %s",
                        self._log_prefix,
                        e,
                        self._log_target(),
                    )
                break

    # ------------------------------------------------------------------
    # K8s-only operations
    # ------------------------------------------------------------------

    def health_check(self, timeout: float = 5.0) -> bool:  # noqa: ARG002
        """Check if we can exec into the pod via a fresh ``echo ok`` command."""
        try:
            k8s = self._get_k8s_client()
            result = k8s_stream(
                k8s.connect_get_namespaced_pod_exec,
                name=self._pod_name,
                namespace=self._namespace,
                container=self._container,
                command=["echo", "ok"],
                stdin=False,
                stdout=True,
                stderr=False,
                tty=False,
            )
            return "ok" in result
        except Exception:
            return False
