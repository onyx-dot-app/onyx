"""The bundled ``gdrive_api.py`` sandbox helper: Drive ``q`` construction and the
native-export-vs-raw-download branch in ``read``. The helper is a standalone
script under the skills dir (not an importable package), so load it by path."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

_HELPER = (
    Path(__file__).resolve().parents[3]
    / "onyx/skills/builtin"
    / "google-drive/gdrive_api.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gdrive_api", _HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gdrive = _load()


def test_build_query_combines_filters_and_excludes_trashed() -> None:
    args = argparse.Namespace(
        text="quarterly report",
        name="Q3",
        mime="application/pdf",
        parent="FOLDER1",
        include_trashed=False,
    )
    q = gdrive._build_query(args)
    assert "fullText contains 'quarterly report'" in q
    assert "name contains 'Q3'" in q
    assert "mimeType = 'application/pdf'" in q
    assert "'FOLDER1' in parents" in q
    assert "trashed = false" in q


def test_build_query_include_trashed_with_no_filters_is_empty() -> None:
    # include_trashed=True drops the default `trashed = false` clause, so with no
    # other filters the query is empty (list everything, trashed included).
    args = argparse.Namespace(
        text=None, name=None, mime=None, parent=None, include_trashed=True
    )
    assert gdrive._build_query(args) == ""


def test_escape_quotes_for_q_literal() -> None:
    assert gdrive._escape("O'Brien") == "O\\'Brien"


def test_read_exports_native_doc_as_markdown(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        gdrive,
        "_req_json",
        lambda _path, _params=None: {
            "id": "D1",
            "name": "Spec",
            "mimeType": "application/vnd.google-apps.document",
        },
    )
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_bytes(path: str, params: dict[str, Any], _max_bytes: int) -> tuple:
        calls.append((path, params))
        return b"# heading", False

    monkeypatch.setattr(gdrive, "_req_bytes", fake_bytes)

    args = argparse.Namespace(file_id="D1", mime=None, max_bytes=1000)
    result = gdrive._read(args)

    assert calls[0][0] == "files/D1/export"
    assert calls[0][1]["mimeType"] == "text/markdown"
    assert result["exportedAs"] == "text/markdown"
    assert result["content"] == "# heading"


def test_read_downloads_binary_via_alt_media(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        gdrive,
        "_req_json",
        lambda _path, _params=None: {
            "id": "F1",
            "name": "notes.txt",
            "mimeType": "text/plain",
        },
    )
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_bytes(path: str, params: dict[str, Any], _max_bytes: int) -> tuple:
        calls.append((path, params))
        return b"hello", False

    monkeypatch.setattr(gdrive, "_req_bytes", fake_bytes)

    args = argparse.Namespace(file_id="F1", mime=None, max_bytes=1000)
    result = gdrive._read(args)

    assert calls[0][0] == "files/F1"
    assert calls[0][1]["alt"] == "media"
    assert result["exportedAs"] is None
    assert result["content"] == "hello"


def test_drives_paginates_and_reports_schema(monkeypatch: Any) -> None:
    """`drives` must honor the documented {items, count, truncated} schema and
    page past the surplus rather than silently dropping it."""
    pages = [
        {"drives": [{"id": str(i)} for i in range(100)], "nextPageToken": "t"},
        {"drives": [{"id": "overflow"}]},
    ]
    seen = iter(pages)
    monkeypatch.setattr(gdrive, "_req_json", lambda *_a, **_k: next(seen))

    args = gdrive._build_parser().parse_args(["drives", "--limit", "100"])
    result = gdrive._dispatch(args)

    assert result["count"] == 100
    assert result["truncated"] is True  # the second page exists but wasn't dropped
    assert len(result["items"]) == 100


def test_upload_creates_and_converts_to_google_doc(
    monkeypatch: Any, tmp_path: Any
) -> None:
    src = tmp_path / "report.md"
    src.write_text("# Report")
    captured: dict[str, Any] = {}

    def fake_upload(
        metadata: dict[str, Any],
        content: bytes,
        content_type: str,
        file_id: str | None = None,
    ) -> dict[str, Any]:
        captured.update(
            metadata=metadata,
            content=content,
            content_type=content_type,
            file_id=file_id,
        )
        return {"id": "NEW", "name": metadata.get("name")}

    monkeypatch.setattr(gdrive, "_upload", fake_upload)

    args = argparse.Namespace(
        path=str(src),
        name="Q3 Report",
        parent="FOLDER1",
        content_type=None,
        convert_to="application/vnd.google-apps.document",
    )
    result = gdrive._upload_cmd(args, file_id=None)

    assert result["ok"] is True
    assert captured["file_id"] is None  # create, not replace
    assert captured["metadata"]["name"] == "Q3 Report"
    assert captured["metadata"]["parents"] == ["FOLDER1"]
    assert captured["metadata"]["mimeType"] == "application/vnd.google-apps.document"
    assert captured["content"] == b"# Report"
    assert captured["content_type"] == "text/markdown"  # guessed from .md


def test_replace_sends_no_metadata_and_targets_file(
    monkeypatch: Any, tmp_path: Any
) -> None:
    src = tmp_path / "data.bin"
    src.write_bytes(b"\x00\x01\x02")
    captured: dict[str, Any] = {}

    def fake_upload(
        metadata: dict[str, Any],
        _content: bytes,
        content_type: str,
        file_id: str | None = None,
    ) -> dict[str, Any]:
        captured.update(metadata=metadata, file_id=file_id, content_type=content_type)
        return {"id": file_id}

    monkeypatch.setattr(gdrive, "_upload", fake_upload)

    args = argparse.Namespace(path=str(src), content_type="application/octet-stream")
    gdrive._upload_cmd(args, file_id="EXISTING")

    assert captured["file_id"] == "EXISTING"
    assert captured["metadata"] == {}  # replace touches content only
    assert captured["content_type"] == "application/octet-stream"


# --- Google Docs API commands ---


def test_docs_base_targets_docs_host() -> None:
    """Docs commands must hit docs.googleapis.com, not the Drive host."""
    assert gdrive._DOCS_BASE == "https://docs.googleapis.com/v1/"
    url = gdrive._url(gdrive._DOCS_BASE, "documents/D1:batchUpdate")
    assert url == "https://docs.googleapis.com/v1/documents/D1:batchUpdate"


def test_get_doc_builds_documents_path(monkeypatch: Any) -> None:
    calls: list[tuple[str, dict[str, Any] | None]] = []

    def fake_docs(
        path: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append((path, params))
        assert method == "GET"
        return {"documentId": "D1", "title": "Spec"}

    monkeypatch.setattr(gdrive, "_req_docs", fake_docs)

    args = gdrive._build_parser().parse_args(["get-doc", "D1"])
    result = gdrive._dispatch(args)

    assert calls[0][0] == "documents/D1"
    assert result["ok"] is True
    assert result["document"]["documentId"] == "D1"


def test_get_doc_passes_fields(monkeypatch: Any) -> None:
    calls: list[tuple[str, dict[str, Any] | None]] = []
    monkeypatch.setattr(
        gdrive,
        "_req_docs",
        lambda path, params=None, **_kwargs: calls.append((path, params)) or {},
    )

    args = gdrive._build_parser().parse_args(
        ["get-doc", "D1", "--fields", "documentId,body"]
    )
    gdrive._dispatch(args)

    assert calls[0][1] == {"fields": "documentId,body"}


def test_insert_text_builds_batch_update_request(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_docs(
        path: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured.update(path=path, method=method, body=body)
        return {"documentId": "D1"}

    monkeypatch.setattr(gdrive, "_req_docs", fake_docs)

    args = gdrive._build_parser().parse_args(
        ["insert-text", "D1", "--index", "5", "--text", "hello"]
    )
    result = gdrive._dispatch(args)

    assert captured["path"] == "documents/D1:batchUpdate"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "requests": [{"insertText": {"location": {"index": 5}, "text": "hello"}}]
    }
    assert result["ok"] is True


def test_append_text_computes_end_index_from_get_doc(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_docs(
        path: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if path.endswith(":batchUpdate"):
            captured.update(path=path, method=method, body=body)
            return {"documentId": "D1"}
        # get-doc response: last structural element endIndex is 42
        return {
            "body": {
                "content": [
                    {"endIndex": 1},
                    {"endIndex": 25},
                    {"endIndex": 42},
                ]
            }
        }

    monkeypatch.setattr(gdrive, "_req_docs", fake_docs)

    args = gdrive._build_parser().parse_args(["append-text", "D1", "--text", "more"])
    result = gdrive._dispatch(args)

    # end index 42 -> insert at 41 to stay in range
    assert result["index"] == 41
    assert captured["body"] == {
        "requests": [{"insertText": {"location": {"index": 41}, "text": "more"}}]
    }


def test_doc_end_index_defaults_to_one_for_empty_body() -> None:
    assert gdrive._doc_end_index({}) == 1
    assert gdrive._doc_end_index({"body": {"content": []}}) == 1


def test_batch_update_passes_through_requests_array(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_docs(
        path: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured.update(path=path, method=method, body=body)
        return {"documentId": "D1", "replies": []}

    monkeypatch.setattr(gdrive, "_req_docs", fake_docs)

    requests_json = (
        '[{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 5}}}]'
    )
    args = gdrive._build_parser().parse_args(["batch-update", "D1", requests_json])
    result = gdrive._dispatch(args)

    assert captured["path"] == "documents/D1:batchUpdate"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "requests": [
            {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 5}}}
        ]
    }
    assert result["ok"] is True


def test_batch_update_rejects_non_array(monkeypatch: Any) -> None:
    monkeypatch.setattr(gdrive, "_req_docs", lambda *_a, **_k: pytest_fail_if_called())

    def pytest_fail_if_called() -> dict[str, Any]:
        raise AssertionError("network should not be called for invalid input")

    args = gdrive._build_parser().parse_args(["batch-update", "D1", '{"a": 1}'])
    result = gdrive._dispatch(args)

    assert result["ok"] is False
    assert result["error"] == "requests_not_array"


def test_batch_update_reads_requests_from_file(monkeypatch: Any, tmp_path: Any) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        gdrive,
        "_req_docs",
        lambda path, body=None, **_kwargs: captured.update(path=path, body=body) or {},
    )
    reqs = tmp_path / "requests.json"
    reqs.write_text('[{"insertText": {"location": {"index": 1}, "text": "x"}}]')

    args = gdrive._build_parser().parse_args(
        ["batch-update", "D1", "--file", str(reqs)]
    )
    gdrive._dispatch(args)

    assert captured["body"]["requests"] == [
        {"insertText": {"location": {"index": 1}, "text": "x"}}
    ]


def test_create_doc_posts_title(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_docs(
        path: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured.update(path=path, method=method, body=body)
        assert body is not None
        return {"documentId": "NEW", "title": body["title"]}

    monkeypatch.setattr(gdrive, "_req_docs", fake_docs)

    args = gdrive._build_parser().parse_args(["create-doc", "--title", "My Doc"])
    result = gdrive._dispatch(args)

    assert captured["path"] == "documents"
    assert captured["method"] == "POST"
    assert captured["body"] == {"title": "My Doc"}
    assert result["document"]["documentId"] == "NEW"
