"""Downloads from connector and code-interpreter servers must stop at a byte
cap while they read, against a real local HTTP server."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest
import requests

from onyx.connectors.confluence import utils as confluence_utils
from onyx.connectors.confluence.source_operations import _OnyxConfluence
from onyx.connectors.highspot.client import HighspotClient
from onyx.connectors.highspot.connector import HighspotConnector
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import PythonToolOverrideKwargs
from onyx.tools.tool_implementations.python import python_tool as python_tool_module
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
    StreamResultEvent,
    WorkspaceFile,
)
from onyx.tools.tool_implementations.python.python_tool import (
    PythonTool,
    _build_output_notice,
)
from onyx.utils.bounded_http import (
    ResponseBodyTimeoutError,
    ResponseTooLargeError,
    read_bounded_body,
)
from tests.unit.onyx.connectors.confluence.confluence_gateway_fakes import (
    gateway_with_client,
)

_CAP_BYTES = 64 * 1024
_SMALL_BODY = b"x" * 1024
_DRIP_SECONDS = 6.0


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002
        return None

    def _send(self, body: bytes, *, declare_length: bool) -> None:
        self.send_response(200)
        if declare_length:
            self.send_header("Content-Length", str(len(body)))
        else:
            self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _drip(self) -> None:
        end = time.monotonic() + _DRIP_SECONDS
        try:
            while time.monotonic() < end:
                self.wfile.write(b"d")
                self.wfile.flush()
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_GET(self) -> None:
        # Route on any path segment: Highspot puts the item id before "/content".
        name = next(
            (
                seg
                for seg in self.path.split("/")
                if seg.split("-")[0]
                in {"small", "declared", "undeclared", "drip", "redirect"}
            ),
            "",
        )
        if name.startswith("small"):
            self._send(_SMALL_BODY, declare_length=True)
        elif name.startswith("declared-big"):
            self._send(b"y" * (_CAP_BYTES * 4), declare_length=True)
        elif name.startswith("undeclared-big"):
            # No Content-Length: only the streamed byte count can stop it.
            self._send(b"z" * (_CAP_BYTES * 4), declare_length=False)
        elif name.startswith("redirect-drip"):
            self.send_response(302)
            self.send_header("Location", "/small")
            self.send_header("Connection", "close")
            self.end_headers()
            self._drip()
        elif name.startswith("drip"):
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            self._drip()
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("path", ["declared-big", "undeclared-big"])
def test_read_bounded_body_rejects_oversize(server_url: str, path: str) -> None:
    with requests.get(f"{server_url}/{path}", stream=True, timeout=5) as response:
        with pytest.raises(ResponseTooLargeError):
            read_bounded_body(response, max_bytes=_CAP_BYTES, deadline_seconds=5)


def test_read_bounded_body_stops_slow_drip(server_url: str) -> None:
    start = time.monotonic()
    with requests.get(f"{server_url}/drip", stream=True, timeout=5) as response:
        with pytest.raises(ResponseBodyTimeoutError):
            read_bounded_body(response, max_bytes=_CAP_BYTES, deadline_seconds=1)
    assert time.monotonic() - start < _DRIP_SECONDS / 2


# --- Confluence ---


def _confluence_gateway(server_url: str) -> Any:
    sdk = mock.Mock()
    sdk.url = server_url
    sdk.session = requests.Session()
    provider = mock.Mock()
    provider.is_dynamic.return_value = False
    provider.get_credentials.return_value = {
        "confluence_username": "user",
        "confluence_access_token": "pat",
    }
    provider.__enter__ = mock.Mock(return_value=None)
    provider.__exit__ = mock.Mock(return_value=None)
    client = _OnyxConfluence(
        is_cloud=False, url=server_url, credentials_provider=provider
    )
    client._confluence = sdk
    client._kwargs = client.shared_base_kwargs
    return gateway_with_client(client, wiki_base=server_url)


def _attachment(name: str, media_type: str) -> dict[str, Any]:
    return {
        "id": f"att-{name}",
        "title": f"{name}.png" if media_type.startswith("image/") else f"{name}.txt",
        "metadata": {"mediaType": media_type},
        # The remote server controls this value; it must not be trusted.
        "extensions": {"fileSize": 1},
        "_links": {"download": f"/download/attachments/1/{name}"},
    }


@pytest.mark.parametrize("media_type", ["text/plain", "image/png"])
@pytest.mark.parametrize("path", ["declared-big", "undeclared-big"])
def test_confluence_attachment_over_cap_is_skipped(
    server_url: str, monkeypatch: pytest.MonkeyPatch, media_type: str, path: str
) -> None:
    monkeypatch.setattr(
        confluence_utils, "CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD", _CAP_BYTES
    )
    store_image = mock.Mock(return_value=(mock.Mock(), "stored"))
    monkeypatch.setattr(confluence_utils, "store_image_and_create_section", store_image)

    result = confluence_utils.process_attachment(
        _confluence_gateway(server_url),
        _attachment(path, media_type),
        parent_content_id="1",
        allow_images=True,
    )

    assert result.error is not None
    assert "download stopped" in result.error
    store_image.assert_not_called()


def test_confluence_attachment_under_cap_is_read(
    server_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        confluence_utils, "CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD", _CAP_BYTES
    )
    monkeypatch.setattr(
        confluence_utils,
        "extract_file_text",
        lambda file, file_name: file.read().decode(),  # noqa: ARG005
    )

    result = confluence_utils.process_attachment(
        _confluence_gateway(server_url),
        _attachment("small", "text/plain"),
        parent_content_id="1",
        allow_images=True,
    )

    assert result.error is None
    assert result.text == _SMALL_BODY.decode()


# --- Highspot ---


def _highspot_connector(server_url: str) -> HighspotConnector:
    connector = HighspotConnector()
    connector._client = HighspotClient(key="k", secret="s", base_url=server_url)
    return connector


def _highspot_item(item_id: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": "Deck",
        "description": "about the deck",
        "content_name": "deck.txt",
        "can_download": True,
        "content_type": "Document",
    }


@pytest.mark.parametrize("item_id", ["declared-big", "undeclared-big"])
def test_highspot_item_over_cap_falls_back_to_metadata(
    server_url: str, monkeypatch: pytest.MonkeyPatch, item_id: str
) -> None:
    from onyx.connectors.highspot import connector as highspot_connector_module

    monkeypatch.setattr(
        highspot_connector_module, "HIGHSPOT_CONNECTOR_SIZE_THRESHOLD", _CAP_BYTES
    )
    extract = mock.Mock(return_value="extracted")
    monkeypatch.setattr(highspot_connector_module, "extract_file_text", extract)

    content = _highspot_connector(server_url)._get_item_content(_highspot_item(item_id))

    assert content == "Deck\nabout the deck"
    extract.assert_not_called()


# --- Code interpreter ---


def test_code_interpreter_download_over_cap_raises(server_url: str) -> None:
    client = CodeInterpreterClient(base_url=server_url)
    with pytest.raises(ResponseTooLargeError):
        client.download_file("undeclared-big", max_bytes=_CAP_BYTES)
    assert client.download_file("small", max_bytes=_CAP_BYTES) == _SMALL_BODY


def _run_python_tool(
    server_url: str, files: list[WorkspaceFile]
) -> tuple[dict[str, Any], mock.Mock, mock.Mock]:
    real_client = CodeInterpreterClient(base_url=server_url)
    client = mock.MagicMock()
    client.download_file.side_effect = real_client.download_file
    client.execute_streaming.return_value = iter(
        [StreamResultEvent(exit_code=0, timed_out=False, duration_ms=1, files=files)]
    )
    ctx = mock.MagicMock()
    ctx.__enter__ = mock.MagicMock(return_value=client)
    ctx.__exit__ = mock.MagicMock(return_value=False)
    file_store = mock.Mock()
    file_store.save_file.side_effect = lambda **_: f"onyx-{uuid4()}"

    tool = PythonTool(tool_id=1, emitter=mock.MagicMock(), chat_session_id=uuid4())
    with (
        mock.patch.object(python_tool_module, "CODE_INTERPRETER_BASE_URL", server_url),
        mock.patch.object(
            python_tool_module, "CodeInterpreterClient", return_value=ctx
        ),
        mock.patch.object(
            python_tool_module, "get_default_file_store", return_value=file_store
        ),
    ):
        response = tool.run(
            placement=Placement(turn_index=0, tab_index=0),
            override_kwargs=PythonToolOverrideKwargs(chat_files=[]),
            code="pass",
        )
    return json.loads(response.llm_facing_response), file_store, client


def _workspace_file(name: str) -> WorkspaceFile:
    return WorkspaceFile(path=f"/out/{name}", kind="file", file_id=name)


def test_python_tool_drops_files_over_byte_cap(server_url: str) -> None:
    with mock.patch.object(
        python_tool_module, "CODE_INTERPRETER_MAX_OUTPUT_BYTES", _CAP_BYTES
    ):
        result, file_store, client = _run_python_tool(
            server_url,
            [_workspace_file("small-1"), _workspace_file("undeclared-big")],
        )

    assert [f["filename"] for f in result["generated_files"]] == ["small-1"]
    assert file_store.save_file.call_count == 1
    assert "/out/undeclared-big" in result["output_notice"]
    deleted = {c.args[0] for c in client.delete_file.call_args_list}
    assert deleted == {"small-1", "undeclared-big"}


def test_python_tool_caps_file_count_and_total_bytes(server_url: str) -> None:
    with (
        mock.patch.object(python_tool_module, "CODE_INTERPRETER_MAX_OUTPUT_FILES", 2),
        mock.patch.object(
            python_tool_module,
            "CODE_INTERPRETER_MAX_OUTPUT_BYTES",
            len(_SMALL_BODY) * 2,
        ),
    ):
        result, file_store, _ = _run_python_tool(
            server_url, [_workspace_file(f"small-{i}") for i in range(4)]
        )

    assert file_store.save_file.call_count == 2
    assert len(result["generated_files"]) == 2
    assert "2 generated file(s) were not saved" in result["output_notice"]


def test_python_tool_has_no_notice_under_caps(server_url: str) -> None:
    result, file_store, _ = _run_python_tool(server_url, [_workspace_file("small-1")])
    assert file_store.save_file.call_count == 1
    assert result["output_notice"] is None


def test_python_tool_byte_cap_drop_does_not_use_file_slot(server_url: str) -> None:
    with (
        mock.patch.object(python_tool_module, "CODE_INTERPRETER_MAX_OUTPUT_FILES", 2),
        mock.patch.object(
            python_tool_module, "CODE_INTERPRETER_MAX_OUTPUT_BYTES", _CAP_BYTES
        ),
    ):
        result, _, _ = _run_python_tool(
            server_url,
            [
                _workspace_file("undeclared-big"),
                _workspace_file("small-1"),
                _workspace_file("small-2"),
            ],
        )

    assert [f["filename"] for f in result["generated_files"]] == [
        "small-1",
        "small-2",
    ]


def test_output_notice_lists_a_bounded_number_of_paths() -> None:
    paths = [f"/out/{'p' * 300}-{i}" for i in range(1000)]
    notice = _build_output_notice(paths)
    assert notice is not None
    assert notice.startswith("1000 generated file(s)")
    assert "and 990 more" in notice
    assert len(notice) < 1500


# --- Redirect bodies ---


def _confluence_download(server_url: str, name: str) -> bytes:
    return _confluence_gateway(server_url).download_attachment(
        attachment=_attachment(name, "text/plain"), parent_content_id="1"
    )


def _highspot_download(server_url: str, name: str) -> bytes:
    client = HighspotClient(key="k", secret="s", base_url=server_url)
    return client.get_item_content(name, max_bytes=_CAP_BYTES)


def _code_interpreter_download(server_url: str, name: str) -> bytes:
    client = CodeInterpreterClient(base_url=server_url)
    return client.download_file(name, max_bytes=_CAP_BYTES)


@pytest.mark.parametrize(
    "download",
    [_confluence_download, _highspot_download, _code_interpreter_download],
)
def test_redirect_body_is_not_read(server_url: str, download: Any) -> None:
    start = time.monotonic()
    assert download(server_url, "redirect-drip") == _SMALL_BODY
    assert time.monotonic() - start < _DRIP_SECONDS / 2
