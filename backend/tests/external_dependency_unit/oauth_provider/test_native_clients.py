import asyncio
import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import AsyncGenerator, Generator, Sequence
from contextlib import asynccontextmanager
from contextvars import Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Never
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pexpect
import pytest
import uvicorn
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import delete
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from onyx.auth.permissions import require_permission
from onyx.auth.schemas import AuthBackend
from onyx.auth.users import auth_backend, fastapi_users, get_redis_strategy
from onyx.configs import app_configs
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.engine.async_sql_engine import reset_sqlalchemy_async_engine
from onyx.db.engine.sql_engine import (
    SqlEngine,
    get_catalog_session,
    get_session_with_current_tenant,
)
from onyx.db.enums import Permission
from onyx.db.models import OAuthProviderClient, OAuthProviderGrant, User
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.oauth_provider import config as oauth_config
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.server.oauth_provider.api import router as user_router
from onyx.server.oauth_provider.protocol import router as protocol_router
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")

_CLI_TIMEOUT_SECONDS = 120
_STRICT_ENV = "MCP_NATIVE_CLIENTS_REQUIRED"
_URL_PATTERN = re.compile(r"https?://[^\s'\"<>\x00-\x1f]+")
_REPO_ROOT = Path(__file__).resolve().parents[4]
_NGINX_IMAGE = os.environ.get("MCP_PROXY_NGINX_IMAGE", "nginx:1.25.5-alpine")
_MCP_NGINX_TEMPLATE = _REPO_ROOT / "deployment/data/nginx/mcp.conf.inc.template"


@dataclass
class NativeRequestEvent:
    method: str
    path: str
    authorization: str | None
    status_code: int | None
    rpc_method: str | None
    response_body: str


@dataclass
class NativeOAuthServer:
    base_url: str
    mcp_path: str
    user_id: str
    cookie_name: str
    session_token: str
    events: list[NativeRequestEvent] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def mcp_url(self) -> str:
        return f"{self.base_url}{self.mcp_path}"

    @property
    def origin(self) -> str:
        return self.base_url

    def record(self, event: NativeRequestEvent) -> None:
        with self._lock:
            self.events.append(event)

    def clear_events(self) -> None:
        with self._lock:
            self.events.clear()

    def saw_authenticated_mcp_request(self) -> bool:
        with self._lock:
            return any(
                method == "POST"
                and path == "/"
                and authorization is not None
                and authorization.startswith("Bearer onyx_oat_")
                for method, path, authorization in (
                    (event.method, event.path, event.authorization)
                    for event in self.events
                )
            )

    def saw_successful_tools_list(self) -> bool:
        with self._lock:
            return any(
                event.method == "POST"
                and event.path == "/"
                and event.status_code == 200
                and event.rpc_method == "tools/list"
                and "search_indexed_documents" in event.response_body
                for event in self.events
            )

    def registered_client_ids(self) -> set[str]:
        client_ids: set[str] = set()
        with self._lock:
            events = list(self.events)
        for event in events:
            if event.method != "POST" or not event.path.endswith("/register"):
                continue
            try:
                payload = json.loads(event.response_body)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("client_id"), str):
                client_ids.add(payload["client_id"])
        return client_ids


def _skip_or_fail(reason: str) -> Never:
    if os.environ.get(_STRICT_ENV):
        pytest.fail(reason)
    pytest.skip(reason)


def _cli_path() -> str:
    node = shutil.which("node")
    entries = [
        str(Path(node).parent) if node else "",
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/usr/bin",
        "/bin",
    ]
    return os.pathsep.join(entry for entry in entries if entry)


def _require_cli(executable: str) -> str:
    path = shutil.which(executable)
    if path is None:
        _skip_or_fail(
            f"{executable} is not available; native MCP OAuth tests require the "
            "Claude Code/Codex CLI binaries."
        )
    return path


def _require_docker() -> str:
    docker = shutil.which("docker")
    if docker is None:
        _skip_or_fail("docker is not available; native MCP OAuth nginx tests need it.")
    probe = subprocess.run(
        [docker, "info"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if probe.returncode != 0:
        _skip_or_fail(
            "docker daemon is not available; native MCP OAuth nginx tests need it. "
            f"{probe.stderr or probe.stdout}"
        )
    return docker


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_http(url: str) -> None:
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError as error:
            last_error = error
        time.sleep(0.1)
    raise RuntimeError(f"server did not become ready at {url}: {last_error!r}")


def _write_nginx_config(config_dir: Path, upstream_port: int) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "mcp.conf.inc").write_text(_MCP_NGINX_TEMPLATE.read_text())
    (config_dir / "mcp_upstream.conf.inc").write_text(
        "upstream mcp_server {\n"
        f"    server host.docker.internal:{upstream_port} fail_timeout=0;\n"
        "}\n"
    )
    (config_dir / "default.conf").write_text(
        "server_tokens off;\n"
        "upstream api_server {\n"
        f"    server host.docker.internal:{upstream_port} fail_timeout=0;\n"
        "}\n"
        "upstream web_server {\n"
        f"    server host.docker.internal:{upstream_port} fail_timeout=0;\n"
        "}\n"
        "map $http_upgrade $connection_upgrade {\n"
        "    default upgrade;\n"
        "    '' close;\n"
        "}\n"
        "include /etc/nginx/conf.d/mcp_upstream.conf.inc;\n"
        "server {\n"
        "    listen 80 default_server;\n"
        "    include /etc/nginx/conf.d/mcp.conf.inc;\n"
        "    location = /nginx-health {\n"
        "        access_log off;\n"
        '        return 200 "ok\\n";\n'
        "    }\n"
        "    location ~ ^/(api|openapi.json)(/.*)?$ {\n"
        "        rewrite ^/api(/.*)$ $1 break;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_set_header X-Forwarded-Host $host;\n"
        "        proxy_set_header X-Forwarded-Port $server_port;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Upgrade $http_upgrade;\n"
        "        proxy_set_header Connection $connection_upgrade;\n"
        "        proxy_buffering off;\n"
        "        proxy_connect_timeout 30s;\n"
        "        proxy_send_timeout 300s;\n"
        "        proxy_read_timeout 300s;\n"
        "        proxy_redirect off;\n"
        "        proxy_pass http://api_server;\n"
        "    }\n"
        "    location / {\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_set_header X-Forwarded-Host $host;\n"
        "        proxy_set_header X-Forwarded-Port $server_port;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_pass http://web_server;\n"
        "    }\n"
        "}\n"
    )


def _start_nginx_proxy(
    docker: str, config_dir: Path, proxy_port: int
) -> subprocess.CompletedProcess[str]:
    command = [
        docker,
        "run",
        "--rm",
        "--detach",
        "--name",
        f"onyx-native-mcp-oauth-{uuid4().hex[:12]}",
        "--publish",
        f"127.0.0.1:{proxy_port}:80",
        "--volume",
        f"{config_dir / 'default.conf'}:/etc/nginx/conf.d/default.conf:ro",
        "--volume",
        f"{config_dir / 'mcp.conf.inc'}:/etc/nginx/conf.d/mcp.conf.inc:ro",
        "--volume",
        f"{config_dir / 'mcp_upstream.conf.inc'}:/etc/nginx/conf.d/mcp_upstream.conf.inc:ro",
    ]
    if sys.platform.startswith("linux"):
        command.extend(["--add-host", "host.docker.internal:host-gateway"])
    command.append(_NGINX_IMAGE)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _jsonrpc_method(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        method = payload.get("method")
        return method if isinstance(method, str) else None
    return None


class NativeCaptureMiddleware:
    def __init__(self, app: ASGIApp, server: NativeOAuthServer) -> None:
        self._app = app
        self._server = server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_messages: list[Message] = []
        request_body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            request_messages.append(message)
            if message["type"] == "http.request":
                request_body.extend(message.get("body", b""))
                more_body = bool(message.get("more_body", False))
            else:
                more_body = False

        replay = iter(request_messages)

        async def replay_receive() -> Message:
            try:
                return next(replay)
            except StopIteration:
                return await receive()

        status_code: int | None = None
        response_body = bytearray()

        async def capture_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
            await send(message)

        await self._app(scope, replay_receive, capture_send)

        headers: Sequence[tuple[bytes, bytes]] = scope.get("headers", [])
        authorization = None
        for key, value in headers:
            if key.lower() == b"authorization":
                authorization = value.decode("latin-1")
                break
        self._server.record(
            NativeRequestEvent(
                method=str(scope["method"]),
                path=str(scope["path"]),
                authorization=authorization,
                status_code=status_code,
                rpc_method=_jsonrpc_method(bytes(request_body)),
                response_body=response_body.decode("utf-8", errors="replace"),
            )
        )


def _approve_consent(server: NativeOAuthServer, authorization_url: str) -> str:
    with httpx.Client(
        base_url=server.base_url,
        cookies={server.cookie_name: server.session_token},
        timeout=30,
    ) as client:
        request_id = parse_qs(urlsplit(authorization_url).query).get("request", [None])[
            0
        ]
        if request_id is None:
            started = client.get(authorization_url, follow_redirects=False)
            assert started.status_code == 302, started.text
            request_id = parse_qs(urlsplit(started.headers["location"]).query).get(
                "request", [None]
            )[0]
        assert request_id is not None, authorization_url
        details = client.get(
            "/api/oauth-provider/consent", params={"request": request_id}
        )
        assert details.status_code == 200, details.text
        approval = client.post(
            "/api/oauth-provider/consent",
            headers={"Origin": server.origin},
            json={
                "request_id": request_id,
                "csrf_token": details.json()["csrf_token"],
                "decision": "allow",
            },
        )
        assert approval.status_code == 200, approval.text
        return str(approval.json()["redirect_url"])


def _cli_text(value: object) -> str:
    assert value is None or isinstance(value, str)
    return value or ""


def _drive_no_browser_login(
    command: list[str], *, env: dict[str, str], server: NativeOAuthServer
) -> str:
    child = pexpect.spawn(
        command[0],
        command[1:],
        env=env,
        encoding="utf-8",
        timeout=_CLI_TIMEOUT_SECONDS,
    )
    output: str = ""
    try:
        authorization_url: str | None = None
        while authorization_url is None:
            try:
                child.expect(_URL_PATTERN)
            except pexpect.EOF as error:
                raise AssertionError(
                    f"CLI exited before printing an authorization URL. Output: "
                    f"{output + _cli_text(child.before)!r}. Server events: {server.events!r}"
                ) from error
            match = child.match
            assert isinstance(match, re.Match)
            candidate = _cli_text(match.group(0))
            output += _cli_text(child.before) + candidate
            parsed = urlsplit(candidate)
            if parse_qs(parsed.query).get("request") or parsed.path.endswith(
                "/authorize"
            ):
                authorization_url = candidate
        callback_url = _approve_consent(server, authorization_url)
        try:
            with httpx.Client(timeout=10) as client:
                client.get(callback_url)
        except httpx.HTTPError:
            pass
        try:
            matched = child.expect([pexpect.EOF, r"Callback URL.*: "], timeout=10)
            if matched == 1:
                child.send(callback_url + "\r")
                child.expect(pexpect.EOF)
        except pexpect.TIMEOUT as error:
            raise AssertionError(
                f"CLI did not finish after callback handoff. Output: "
                f"{output + _cli_text(child.before)!r}. Callback: {callback_url!r}. "
                f"Server events: {server.events!r}"
            ) from error
        output += _cli_text(child.before)
    finally:
        if child.isalive():
            child.terminate(force=True)
    assert child.exitstatus == 0, output
    return output


def _run_cli(
    command: list[str], *, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=_CLI_TIMEOUT_SECONDS,
        env=env,
        check=False,
    )


def _send_codex_app_server_request(
    process: subprocess.Popen[str],
    request_id: int,
    method: str,
    params: dict[str, object],
) -> None:
    assert process.stdin is not None
    process.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        + "\n"
    )
    process.stdin.flush()


def _read_codex_app_server_response(
    process: subprocess.Popen[str], request_id: int
) -> dict[str, object]:
    assert process.stdout is not None
    deadline = time.monotonic() + _CLI_TIMEOUT_SECONDS
    messages: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        ready, _, _ = select.select(
            [process.stdout], [], [], deadline - time.monotonic()
        )
        if not ready:
            break
        line = process.stdout.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            messages.append(message)
            if message.get("id") == request_id:
                if "error" in message:
                    raise AssertionError(
                        f"Codex app-server request {request_id} failed: {message!r}. "
                        f"Messages: {messages!r}"
                    )
                return message
    raise AssertionError(
        f"Codex app-server did not answer request {request_id}. Messages: {messages!r}"
    )


def _codex_discover_mcp_tools(
    codex: str,
    config: list[str],
    *,
    env: dict[str, str],
    server_name: str,
) -> dict[str, object]:
    process = subprocess.Popen(
        [codex, "app-server", *config, "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        _send_codex_app_server_request(
            process,
            1,
            "initialize",
            {
                "clientInfo": {
                    "name": "onyx-native-mcp-oauth-test",
                    "version": "0",
                },
                "capabilities": {},
            },
        )
        _read_codex_app_server_response(process, 1)
        _send_codex_app_server_request(
            process,
            2,
            "mcpServerStatus/list",
            {
                "serverName": server_name,
                "detail": "toolsAndAuthOnly",
                "limit": 1,
            },
        )
        response = _read_codex_app_server_response(process, 2)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return response


@pytest.fixture(scope="module")
def native_oauth_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[NativeOAuthServer, None, None]:
    docker = _require_docker()
    tenant_token: Token[str | None] = CURRENT_TENANT_ID_CONTEXTVAR.set(
        POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    )
    monkeypatch = pytest.MonkeyPatch()
    event_loop = asyncio.new_event_loop()
    upstream_port = _free_port()
    proxy_port = _free_port()
    upstream_url = f"http://127.0.0.1:{upstream_port}"
    public_url = f"http://127.0.0.1:{proxy_port}"
    monkeypatch.setattr(app_configs, "WEB_DOMAIN", public_url)
    monkeypatch.setattr(app_configs, "AUTH_BACKEND", AuthBackend.REDIS)
    monkeypatch.setattr(
        oauth_config,
        "OAUTH_PROVIDER_SETTINGS",
        oauth_config.load_oauth_provider_settings(),
    )
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    db_session_context = get_session_with_current_tenant()
    db_session = db_session_context.__enter__()
    user = create_test_user(db_session, "mcp_native_client", assign_default_group=False)
    user.effective_permissions = [
        Permission.READ_SEARCH.value,
        Permission.CREATE_USER_API_KEYS.value,
    ]
    db_session.commit()
    strategy = get_redis_strategy()
    session_token = event_loop.run_until_complete(strategy.write_token(user))
    server_state = NativeOAuthServer(
        base_url=public_url,
        mcp_path="/mcp",
        user_id=str(user.id),
        cookie_name=FASTAPI_USERS_AUTH_COOKIE_NAME,
        session_token=session_token,
    )

    from onyx.mcp_server import api as mcp_api
    from onyx.mcp_server import auth as mcp_auth

    def _test_api_server_url(respect_env_override_if_set: bool = False) -> str:
        if respect_env_override_if_set:
            pass
        return upstream_url

    monkeypatch.setattr(
        mcp_auth,
        "build_api_server_url_for_http_requests",
        _test_api_server_url,
    )
    monkeypatch.setattr(mcp_api.mcp_server, "auth", mcp_auth.build_mcp_server_auth())
    mcp_child_app = mcp_api.create_mcp_fastapi_app()

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        async with mcp_child_app.router.lifespan_context(mcp_child_app):
            try:
                yield
            finally:
                await reset_sqlalchemy_async_engine()

    app = FastAPI(lifespan=_lifespan)
    register_onyx_exception_handlers(app)

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"success": True})

    app.include_router(protocol_router)
    app.include_router(user_router)
    app.include_router(
        fastapi_users.get_refresh_router(auth_backend, requires_verification=False),
        prefix="/auth",
    )
    app.dependency_overrides[auth_backend.get_strategy] = lambda: strategy

    @app.post("/search")
    def search(
        authenticated_user: User = Depends(require_permission(Permission.READ_SEARCH)),
    ) -> dict[str, str]:
        return {"user_id": str(authenticated_user.id)}

    app.mount("/", mcp_child_app)

    config = uvicorn.Config(
        NativeCaptureMiddleware(app, server_state),
        host="0.0.0.0",
        port=upstream_port,
        log_level="warning",
        lifespan="on",
    )
    uvicorn_server = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    container_id = ""

    try:
        _wait_for_http(f"{upstream_url}/health")

        nginx_dir = tmp_path_factory.mktemp("native-nginx")
        _write_nginx_config(nginx_dir, upstream_port)
        nginx = _start_nginx_proxy(docker, nginx_dir, proxy_port)
        container_id = nginx.stdout.strip()
        if nginx.returncode != 0:
            _skip_or_fail(
                f"failed to start Docker nginx proxy with {_NGINX_IMAGE}: "
                f"{nginx.stderr or nginx.stdout}"
            )
        _wait_for_http(f"{public_url}/nginx-health")
        yield server_state
    finally:
        if container_id:
            subprocess.run(
                [docker, "rm", "--force", container_id],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        uvicorn_server.should_exit = True
        thread.join(timeout=10)
        event_loop.run_until_complete(strategy.destroy_token(session_token, user))
        redis_client = event_loop.run_until_complete(get_async_redis_connection())
        try:
            event_loop.run_until_complete(
                redis_client.delete(f"{strategy.key_prefix}{session_token}")
            )
        finally:
            event_loop.run_until_complete(redis_client.aclose())
        db_session.rollback()
        db_session.execute(
            delete(OAuthProviderGrant).where(OAuthProviderGrant.user_id == user.id)
        )
        delete_test_user(db_session, user)
        db_session.commit()
        with get_catalog_session() as catalog:
            for client_id in server_state.registered_client_ids():
                client = catalog.get(OAuthProviderClient, client_id)
                if client is not None:
                    catalog.delete(client)
            catalog.commit()
        db_session_context.__exit__(None, None, None)
        event_loop.close()
        monkeypatch.undo()
        CURRENT_TENANT_ID_CONTEXTVAR.reset(tenant_token)


def _codex_config(server_name: str, server: NativeOAuthServer) -> list[str]:
    return [
        "-c",
        'mcp_oauth_credentials_store="file"',
        "-c",
        f'mcp_servers.{server_name}={{url="{server.mcp_url}"}}',
    ]


@pytest.mark.parametrize("registration", ["dcr", "auto"])
@pytest.mark.parametrize("mcp_path", ["/mcp", "/mcp/"], ids=["bare-mcp", "slash-mcp"])
def test_codex_mcp_login_exchanges_tokens_and_reaches_mcp(
    native_oauth_server: NativeOAuthServer,
    tmp_path: Path,
    registration: str,
    mcp_path: str,
) -> None:
    codex = _require_cli("codex")
    server_name = f"onyx_native_{registration}_{uuid4().hex[:8]}"
    env = {
        **os.environ,
        "PATH": _cli_path(),
        "NO_COLOR": "1",
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    native_oauth_server.mcp_path = mcp_path
    config = _codex_config(server_name, native_oauth_server)
    native_oauth_server.clear_events()
    try:
        output = _drive_no_browser_login(
            [
                codex,
                "mcp",
                *config,
                "login",
                "--no-browser",
                "--oauth-client-registration",
                registration,
                server_name,
            ],
            env=env,
            server=native_oauth_server,
        )
        assert "success" in output.lower() or "logged in" in output.lower()
        status = _codex_discover_mcp_tools(
            codex,
            config,
            env=env,
            server_name=server_name,
        )
        assert "search_indexed_documents" in json.dumps(status)
        assert native_oauth_server.saw_successful_tools_list()
    finally:
        _run_cli([codex, "mcp", *config, "logout", server_name], env=env)


@pytest.mark.parametrize("mcp_path", ["/mcp", "/mcp/"], ids=["bare-mcp", "slash-mcp"])
def test_claude_mcp_login_and_get_discovers_tools(
    native_oauth_server: NativeOAuthServer, tmp_path: Path, mcp_path: str
) -> None:
    claude = _require_cli("claude")
    server_name = f"onyx-native-claude-{uuid4().hex[:8]}"
    env = {
        **os.environ,
        "PATH": _cli_path(),
        "NO_COLOR": "1",
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude-config"),
    }
    native_oauth_server.mcp_path = mcp_path
    add = _run_cli(
        [
            claude,
            "mcp",
            "add",
            "--transport",
            "http",
            "--scope",
            "user",
            server_name,
            native_oauth_server.mcp_url,
        ],
        env=env,
    )
    assert add.returncode == 0, add.stderr + add.stdout
    try:
        _drive_no_browser_login(
            [claude, "mcp", "login", "--no-browser", server_name],
            env=env,
            server=native_oauth_server,
        )
        native_oauth_server.clear_events()
        details = _run_cli([claude, "mcp", "get", server_name], env=env)
        assert details.returncode == 0, details.stderr + details.stdout
        assert "Connected" in details.stdout
        assert native_oauth_server.saw_successful_tools_list()
    finally:
        _run_cli([claude, "mcp", "logout", server_name], env=env)
        _run_cli([claude, "mcp", "remove", "--scope", "user", server_name], env=env)
