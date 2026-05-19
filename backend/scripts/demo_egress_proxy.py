"""DEMO egress interceptor — validates the external-app credential flow
end-to-end. NOT production-grade (a separate production interceptor is
being built).

What it does: acts as an HTTPS forward proxy. For every intercepted
request it rebuilds the full URL, calls
`get_external_app_credentials(db, user_id, url)` (the same resolver the
real interceptor will use — regex-matches the URL against each enabled
ExternalApp's `upstream_url_patterns`, then fills the app's
`auth_template` with the user's stored credentials), injects the
resulting headers, and forwards upstream.

Demo-only simplifications (do NOT ship):
  * Scoped to ONE user via --user-id (production maps sandbox -> user).
  * Self-signed CA minted on first run; clients must trust it.
  * Blocking, full-body buffering, no chunked-request support, minimal
    error handling, no connection reuse / streaming.

Run (from backend/, with the venv; .env lives at the repo root):
  python -m dotenv -f ../.vscode/.env run -- \\
      python scripts/demo_egress_proxy.py --user-id <UUID> [--port 8888]

Point a client at it (the bundled wrappers use stdlib urllib, which
honors these):
  export HTTPS_PROXY=http://127.0.0.1:8888
  export SSL_CERT_FILE=<printed CA path>
  python .../slack_api.py channels      # creds injected if Slack matches
"""

import argparse
import datetime
import http.client
import ssl
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.external_app import get_external_app_credentials
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

_HOP_BY_HOP = {
    "connection",
    "proxy-connection",
    "proxy-authorization",
    "keep-alive",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class _CA:
    """Self-signed CA + on-demand per-host leaf certs (cached)."""

    def __init__(self, ca_dir: Path) -> None:
        ca_dir.mkdir(parents=True, exist_ok=True)
        self.cert_path = ca_dir / "onyx-demo-egress-ca.pem"
        self._key_path = ca_dir / "onyx-demo-egress-ca-key.pem"
        self._leaf_dir = ca_dir / "leaves"
        self._leaf_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        if self.cert_path.exists() and self._key_path.exists():
            loaded = serialization.load_pem_private_key(
                self._key_path.read_bytes(), password=None
            )
            assert isinstance(loaded, rsa.RSAPrivateKey)  # we only mint RSA
            self._key: rsa.RSAPrivateKey = loaded
            self._cert = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
        else:
            self._key, self._cert = self._mint_ca()
            self._key_path.write_bytes(
                self._key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption(),
                )
            )
            self.cert_path.write_bytes(
                self._cert.public_bytes(serialization.Encoding.PEM)
            )

    def _mint_ca(self) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Onyx Demo Egress CA")]
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .sign(key, hashes.SHA256())
        )
        return key, cert

    def leaf(self, host: str) -> tuple[str, str]:
        """Return (cert_path, key_path) for *host*, minting if needed."""
        safe = host.replace(":", "_").replace("/", "_")
        cp = self._leaf_dir / f"{safe}.pem"
        kp = self._leaf_dir / f"{safe}-key.pem"
        with self._lock:
            if cp.exists() and kp.exists():
                return str(cp), str(kp)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (
                x509.CertificateBuilder()
                .subject_name(
                    x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
                )
                .issuer_name(self._cert.subject)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=825))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), False)
                .sign(self._key, hashes.SHA256())
            )
            kp.write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption(),
                )
            )
            cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            return str(cp), str(kp)


# Set by main() before the server starts.
_CA_STORE: _CA
_USER_ID: UUID
_TENANT_ID: str


def _resolve_headers(url: str) -> dict[str, str]:
    with get_session_with_tenant(tenant_id=_TENANT_ID) as db:
        creds = get_external_app_credentials(db, _USER_ID, url)
    return {str(k): str(v) for k, v in (creds or {}).items()}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # quieter
        print(f"[demo-egress] {format % args}")

    def do_CONNECT(self) -> None:
        host, _, port_s = self.path.partition(":")
        port = int(port_s or 443)
        self.send_response(200, "Connection Established")
        self.end_headers()

        cert_path, key_path = _CA_STORE.leaf(host)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        try:
            tls = ctx.wrap_socket(self.connection, server_side=True)
        except ssl.SSLError as e:
            print(f"[demo-egress] TLS handshake failed for {host}: {e}")
            return

        try:
            self._intercept(tls, host, port)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def _intercept(self, tls: ssl.SSLSocket, host: str, port: int) -> None:
        rfile = tls.makefile("rb")
        request_line = rfile.readline().decode("latin-1").strip()
        if not request_line:
            return
        method, path, _ = request_line.split(" ", 2)

        headers = http.client.parse_headers(rfile)
        body = b""
        if (length := headers.get("Content-Length")) is not None:
            body = rfile.read(int(length))

        url = f"https://{host}{'' if port == 443 else f':{port}'}{path}"
        injected = _resolve_headers(url)
        print(
            f"[demo-egress] {method} {url} -> "
            f"{'inject ' + ','.join(injected) if injected else 'no match'}"
        )

        out: dict[str, str] = {}
        for k, v in headers.items():
            if k.lower() in _HOP_BY_HOP or k.lower() in {h.lower() for h in injected}:
                continue
            out[k] = v
        out.update(injected)
        out["Host"] = host
        if body:
            out["Content-Length"] = str(len(body))

        upstream = http.client.HTTPSConnection(
            host, port, context=ssl.create_default_context(), timeout=30
        )
        try:
            upstream.request(method, path, body=body or None, headers=out)
            resp = upstream.getresponse()
            payload = resp.read()
        except (OSError, http.client.HTTPException) as e:
            tls.sendall(
                b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
            print(f"[demo-egress] upstream error for {url}: {e}")
            return
        finally:
            upstream.close()

        lines = [f"HTTP/1.1 {resp.status} {resp.reason}"]
        for k, v in resp.getheaders():
            if k.lower() in _HOP_BY_HOP or k.lower() == "content-length":
                continue
            lines.append(f"{k}: {v}")
        lines.append(f"Content-Length: {len(payload)}")
        lines.append("Connection: close")
        tls.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        tls.sendall(payload)


def main() -> None:
    global _CA_STORE, _USER_ID, _TENANT_ID
    p = argparse.ArgumentParser(description="DEMO egress credential interceptor.")
    p.add_argument("--user-id", required=True, type=UUID)
    p.add_argument("--tenant-id", default=POSTGRES_DEFAULT_SCHEMA)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8888)
    p.add_argument(
        "--ca-dir",
        default=str(Path.home() / ".onyx-demo-egress"),
        help="where the demo CA is stored/reused",
    )
    args = p.parse_args()

    SqlEngine.init_engine(pool_size=5, max_overflow=2)
    _CA_STORE = _CA(Path(args.ca_dir))
    _USER_ID = args.user_id
    _TENANT_ID = args.tenant_id

    print(f"[demo-egress] CA cert: {_CA_STORE.cert_path}")
    print(
        "[demo-egress] trust it in the client, e.g. "
        f"export SSL_CERT_FILE={_CA_STORE.cert_path}"
    )
    print(
        f"[demo-egress] proxy listening on http://{args.host}:{args.port} "
        f"(user={_USER_ID}, tenant={_TENANT_ID})"
    )
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
