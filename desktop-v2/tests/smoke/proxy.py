"""A reverse proxy that the smoke test points the app at.

It forwards plain HTTP on 127.0.0.1 to the real server (often HTTPS), so the
test can take "the server" down and bring it back without touching it. It also
models a self-hosted server on plain HTTP: the app allows `http://` only for
loopback hosts.
"""

from __future__ import annotations

import http.client
import http.server
import socket
import ssl
import threading
import urllib.parse

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}


class ToggleProxy:
    def __init__(self, upstream: str, port: int) -> None:
        parsed = urllib.parse.urlsplit(upstream.rstrip("/"))
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"bad upstream {upstream!r}")
        self.upstream = f"{parsed.scheme}://{parsed.netloc}"
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._netloc = parsed.netloc
        self._upstream_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._server: http.server.ThreadingHTTPServer | None = None
        self.requests: list[str] = []

    def _connection(self) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._host,
                self._upstream_port,
                timeout=120,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(self._host, self._upstream_port, timeout=120)

    def _rewrite_out(self, value: str) -> str:
        return value.replace(self.url, self.upstream)

    def _rewrite_in(self, value: str) -> str:
        return value.replace(self.upstream, self.url)

    def _open_upgrade(self, request_head: str) -> tuple[socket.socket, bytes]:
        """Sends an upgrade request upstream; returns the socket and the response head."""
        raw = socket.create_connection((self._host, self._upstream_port), timeout=120)
        upstream: socket.socket = raw
        if self._scheme == "https":
            upstream = ssl.create_default_context().wrap_socket(
                raw, server_hostname=self._host
            )
        upstream.sendall(request_head.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            data = upstream.recv(65536)
            if not data:
                break
            head += data
        return upstream, head

    def start(self) -> None:
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _forward(self) -> None:
                if self.headers.get("Upgrade", "").lower() == "websocket":
                    self._tunnel()
                    return
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else None
                headers = {
                    k: proxy._rewrite_out(v)
                    for k, v in self.headers.items()
                    if k.lower() not in HOP_BY_HOP
                }
                headers["Host"] = proxy._netloc
                headers["Accept-Encoding"] = "identity"
                upstream = proxy._connection()
                try:
                    upstream.request(
                        self.command, self.path, body=body, headers=headers
                    )
                    response = upstream.getresponse()
                    proxy.requests.append(
                        f"{self.command} {self.path} -> {response.status}"
                    )
                    self.send_response(response.status, response.reason)
                    for key, value in response.getheaders():
                        lower = key.lower()
                        if lower in HOP_BY_HOP:
                            continue
                        if lower == "location":
                            value = proxy._rewrite_in(value)
                        if lower == "set-cookie":
                            value = value.replace("; Secure", "").replace(
                                "; secure", ""
                            )
                        self.send_header(key, value)
                    if self.command == "HEAD" or response.status in (204, 304):
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    # Chunked, so streamed answers (SSE) arrive as they are made.
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    while chunk := response.read1(65536):
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                except (OSError, http.client.HTTPException) as error:
                    proxy.requests.append(f"{self.command} {self.path} -> {error!r}")
                    self.close_connection = True
                finally:
                    upstream.close()

            def _tunnel(self) -> None:
                """Pipes a WebSocket upgrade both ways (a dev server's HMR needs it)."""
                proxy.requests.append(f"{self.command} {self.path} -> upgrade")
                lines = [
                    f"{self.command} {self.path} HTTP/1.1",
                    f"Host: {proxy._netloc}",
                ]
                for key, value in self.headers.items():
                    if key.lower() != "host":
                        lines.append(f"{key}: {proxy._rewrite_out(value)}")
                upstream, head = proxy._open_upgrade("\r\n".join(lines) + "\r\n\r\n")
                status = head.split(b"\r\n", 1)[0]
                if b" 101 " not in status + b" ":
                    # A refused upgrade must not leave a raw pipe that the client reuses
                    # for its next request, which would reach the server unrewritten.
                    code = (
                        status.split(b" ")[1].decode() if status.count(b" ") else "502"
                    )
                    self.connection.sendall(
                        f"HTTP/1.1 {code} Upgrade refused\r\n"
                        "Content-Length: 0\r\nConnection: close\r\n\r\n".encode()
                    )
                    upstream.close()
                    self.close_connection = True
                    return
                self.connection.sendall(head)
                upstream.settimeout(None)
                client = self.connection
                client.settimeout(None)

                back = threading.Thread(
                    target=_pipe, args=(upstream, client), daemon=True
                )
                back.start()
                _pipe(client, upstream)
                back.join()
                upstream.close()
                self.close_connection = True

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _forward
            do_OPTIONS = _forward

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ARG002
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        server.daemon_threads = True
        self._server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        """Closes the socket, so new connections are refused."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def running(self) -> bool:
        return self._server is not None


def _pipe(source: socket.socket, sink: socket.socket) -> None:
    """Copies bytes one way until either side closes, then closes both."""
    try:
        while data := source.recv(65536):
            sink.sendall(data)
    except OSError:
        pass
    finally:
        for end in (source, sink):
            try:
                end.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
