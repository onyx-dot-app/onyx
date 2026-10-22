from collections.abc import Iterator
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from stat import S_IMODE
from unittest.mock import MagicMock, patch

import pytest
import requests
from dropbox.files import FileMetadata

from onyx.connectors.airtable import airtable_connector as airtable
from onyx.connectors.cross_connector_utils.download import download_file
from onyx.connectors.dropbox import connector as dropbox
from onyx.connectors.zulip import connector as zulip


def test_dropbox_skips_oversized_files_before_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dropbox, "DROPBOX_CONNECTOR_SIZE_THRESHOLD", 4, raising=False)
    connector = dropbox.DropboxConnector()
    client = MagicMock()
    connector.dropbox_client = client
    now = datetime.now(timezone.utc)
    client.files_list_folder.return_value = MagicMock(
        entries=[
            FileMetadata(
                name=f"{size}.txt",
                id=f"id:{size}",
                client_modified=now,
                server_modified=now,
                rev="123456789",
                size=size,
                path_display=f"/{size}.txt",
            )
            for size in (5, 4)
        ],
        has_more=False,
    )
    with (
        patch.object(connector, "_download_file", return_value=b"text") as download,
        patch.object(connector, "_get_shared_link", return_value="https://example.com"),
        patch.object(dropbox, "extract_file_text", return_value="text"),
    ):
        batches = list(connector.load_from_state())
    download.assert_called_once_with("/4.txt")
    assert len(batches[0]) == 1


def _extract_attachment(
    connector: airtable.AirtableConnector, size: int
) -> list[tuple[str, str]]:
    return connector._extract_field_values(
        "fldTest",
        "files",
        [
            {
                "id": "attTest",
                "url": "https://example.com/file",
                "filename": "file.txt",
                "size": size,
            }
        ],
        "multipleAttachments",
        "appTest",
        "tblTest",
        None,
        "recTest",
    )


def test_airtable_skips_declared_oversized_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        airtable, "AIRTABLE_ATTACHMENT_SIZE_THRESHOLD", 4, raising=False
    )
    connector = airtable.AirtableConnector()
    with patch.object(airtable.requests, "get") as get:
        assert _extract_attachment(connector, 5) == []
    get.assert_not_called()


@pytest.mark.parametrize("refresh", [False, True])
def test_airtable_stops_oversized_stream_and_accepts_boundary(
    monkeypatch: pytest.MonkeyPatch,
    refresh: bool,
) -> None:
    monkeypatch.setattr(
        airtable, "AIRTABLE_ATTACHMENT_SIZE_THRESHOLD", 4, raising=False
    )
    connector = airtable.AirtableConnector()
    client = MagicMock()
    connector._airtable_client = client
    client.table.return_value.get.return_value = {
        "fields": {
            "files": [{"filename": "file.txt", "url": "https://example.com/refreshed"}]
        }
    }
    response = MagicMock()
    response.__enter__.return_value = response
    response.content = b"oversized body"
    consumed: list[bytes] = []

    def chunks(chunk_size: int) -> Iterator[bytes]:
        assert chunk_size > 0
        for chunk in (b"abcd", b"e", b"must not read"):
            consumed.append(chunk)
            yield chunk

    response.iter_content.side_effect = chunks
    expired = MagicMock()
    expired.__enter__.return_value = expired
    expired.status_code = 410
    expired.raise_for_status.side_effect = requests.HTTPError(response=expired)
    with (
        patch.object(
            airtable.requests,
            "get",
            side_effect=[expired, response] if refresh else [response],
        ) as get,
        patch.object(airtable, "extract_file_text", return_value="text") as extract,
    ):
        assert _extract_attachment(connector, 0) == []
        extract.assert_not_called()
        assert consumed == [b"abcd", b"e"]
        assert all(call.kwargs["stream"] for call in get.call_args_list)
        response.__exit__.assert_called_once()
        response.iter_content.side_effect = None
        response.iter_content.return_value = iter([b"abcd"])
        get.side_effect = [response]
        assert len(_extract_attachment(connector, 4)) == 1


@pytest.mark.parametrize("client_fails", [False, True])
def test_zulip_credentials_are_private_and_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client_fails: bool,
) -> None:
    monkeypatch.setattr(zulip.tempfile, "tempdir", str(tmp_path))
    paths: list[Path] = []
    modes: list[int] = []

    def build_client(config_file: str) -> MagicMock:
        path = Path(config_file)
        paths.append(path)
        modes.append(S_IMODE(path.stat().st_mode))
        assert path.read_text() == "[api]\nemail=user@example.com"
        if client_fails:
            raise RuntimeError("client setup failed")
        return MagicMock()

    with patch.object(zulip, "Client", side_effect=build_client):
        for _ in range(2):
            connector = zulip.ZulipConnector("test", "https://example.com")
            if client_fails:
                with pytest.raises(RuntimeError, match="client setup failed"):
                    connector.load_credentials(
                        {"zuliprc_content": "[api] email=user@example.com"}
                    )
            else:
                connector.load_credentials(
                    {"zuliprc_content": "[api] email=user@example.com"}
                )
    assert all(not path.exists() for path in paths)
    assert modes == [0o600, 0o600]
    assert paths[0] != paths[1]


class _TrackedDownloadBody(BytesIO):
    bytes_read: int = 0

    def read(self, size: int | None = -1) -> bytes:
        chunk: bytes = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


@pytest.mark.parametrize("max_size_bytes", [0, 4])
def test_download_bounds_read_size_for_small_caps(max_size_bytes: int) -> None:
    body: _TrackedDownloadBody = _TrackedDownloadBody(b"x" * 1024)
    response: requests.Response = requests.Response()
    response.status_code = 200
    response.raw = body
    with patch("requests.get", return_value=response):
        assert (
            download_file(
                "https://example.com/file",
                max_size_bytes=max_size_bytes,
                timeout_seconds=60,
            )
            is None
        )
    assert body.bytes_read == max_size_bytes + 1
    assert body.closed
