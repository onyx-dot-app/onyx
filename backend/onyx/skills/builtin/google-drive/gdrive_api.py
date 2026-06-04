#!/usr/bin/env python3
"""Google Drive wrapper for the Onyx Craft sandbox.

Common operations exposed as subcommands. Output is JSON on stdout. No auth is
handled here: the sandbox egress proxy injects the connected user's bearer token.
Writes (create/upload/edit/delete) may pause for user approval at the proxy.
"""

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://www.googleapis.com/drive/v3/"
# Content uploads use a separate host path from the metadata/JSON API.
_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3/"
_PAGE_SIZE = 100
_DEFAULT_LIMIT = 100
_HTTP_TIMEOUT_SECONDS = 180
# Cap a single `read` so a huge file can't blow up the agent's context.
_DEFAULT_MAX_BYTES = 5_000_000
_UPLOAD_BOUNDARY = "onyx-gdrive-boundary-7c1f"
_FOLDER_MIME = "application/vnd.google-apps.folder"
# Explicit content-types for the text formats Craft produces — `mimetypes` is
# platform-dependent and notably misses `.md`, which Drive needs to convert
# markdown into a Google Doc.
_CONTENT_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
}

# Curated field set for list results — enough to identify and locate a file
# without dragging in Drive's very large default metadata blob.
_FILE_FIELDS = (
    "id,name,mimeType,modifiedTime,size,parents,"
    "owners(displayName,emailAddress),webViewLink"
)
_GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."
# What to export each Google-native type to when reading its contents as text.
_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/markdown",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_DEFAULT_EXPORT_MIME = "text/plain"


def _prune(value: Any) -> Any:
    """Recursively drop None / "" / [] / {} so LLM-facing output stays small.
    Booleans and 0 are kept — they carry signal."""
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _seg(value: str) -> str:
    """URL-encode a single path segment (ids may contain special chars)."""
    return urllib.parse.quote(value, safe="")


def _url(base: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = base + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url += "?" + urllib.parse.urlencode(clean)
    return url


def _req_json(
    path: str,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a Drive JSON endpoint; return parsed JSON ({} on empty/204)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"} if data else {}
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        _url(_BASE, path, params), data=data, method=method, headers=headers
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _req_bytes(path: str, params: dict[str, Any], max_bytes: int) -> tuple[bytes, bool]:
    """GET raw bytes (export / alt=media). Returns (bytes, truncated)."""
    req = urllib.request.Request(_url(_BASE, path, params), method="GET")  # noqa: S310
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        return data[:max_bytes], True
    return data, False


def _upload(
    metadata: dict[str, Any],
    content: bytes,
    content_type: str,
    file_id: str | None = None,
) -> dict[str, Any]:
    """multipart/related create (POST) or content-replace (PATCH) against the
    upload host. Returns the created/updated file's metadata."""
    b = _UPLOAD_BOUNDARY
    parts = [
        f"--{b}\r\n".encode(),
        b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
        json.dumps(metadata).encode("utf-8"),
        f"\r\n--{b}\r\n".encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        content,
        f"\r\n--{b}--\r\n".encode(),
    ]
    method = "PATCH" if file_id else "POST"
    path = f"files/{_seg(file_id)}" if file_id else "files"
    url = _url(
        _UPLOAD_BASE,
        path,
        {
            "uploadType": "multipart",
            "fields": _FILE_FIELDS,
            "supportsAllDrives": "true",
        },
    )
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        url,
        data=b"".join(parts),
        method=method,
        headers={"Content-Type": f"multipart/related; boundary={b}"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _shared_drive_params(shared: bool) -> dict[str, Any]:
    """Params needed to see items in shared drives, not just My Drive."""
    if not shared:
        return {}
    return {
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
        "corpora": "allDrives",
    }


def _paginate(
    path: str, list_key: str, params: dict[str, Any], limit: int
) -> dict[str, Any]:
    """Walk a Drive list endpoint (`<list_key>` + `nextPageToken`) up to `limit`."""
    items: list[Any] = []
    token: str | None = None
    while True:
        q = dict(params, pageSize=min(_PAGE_SIZE, limit - len(items)))
        if token:
            q["pageToken"] = token
        resp = _req_json(path, params=q)
        items.extend(resp.get(list_key) or [])
        token = resp.get("nextPageToken")
        if len(items) >= limit:
            return {
                "ok": True,
                "items": items[:limit],
                "count": limit,
                "truncated": bool(token),
            }
        if not token:
            break
    return {"ok": True, "items": items, "count": len(items), "truncated": False}


def _escape(value: str) -> str:
    """Escape a value for a Drive `q` string literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _build_query(a: argparse.Namespace) -> str:
    """Assemble a Drive `q` from the search flags."""
    clauses: list[str] = []
    if getattr(a, "text", None):
        clauses.append(f"fullText contains '{_escape(a.text)}'")
    if getattr(a, "name", None):
        clauses.append(f"name contains '{_escape(a.name)}'")
    if getattr(a, "mime", None):
        clauses.append(f"mimeType = '{_escape(a.mime)}'")
    if getattr(a, "parent", None):
        clauses.append(f"'{_escape(a.parent)}' in parents")
    if not getattr(a, "include_trashed", False):
        clauses.append("trashed = false")
    return " and ".join(clauses)


def _list(query: str, a: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q": query or None,
        "fields": f"nextPageToken, files({_FILE_FIELDS})",
        "orderBy": "modifiedTime desc",
        "spaces": "drive",
        **_shared_drive_params(getattr(a, "shared_drives", False)),
    }
    return _paginate("files", "files", params, a.limit)


def _read(a: argparse.Namespace) -> dict[str, Any]:
    """Fetch a file's contents: export Google-native docs to text, otherwise
    download the raw bytes via alt=media."""
    fid = _seg(a.file_id)
    meta = _req_json(
        f"files/{fid}",
        {"fields": "id,name,mimeType,size", **_shared_drive_params(True)},
    )
    mime = meta.get("mimeType", "")
    native = mime.startswith(_GOOGLE_NATIVE_PREFIX)
    if native:
        export_mime = a.mime or _EXPORT_MIME.get(mime, _DEFAULT_EXPORT_MIME)
        data, truncated = _req_bytes(
            f"files/{fid}/export", {"mimeType": export_mime}, a.max_bytes
        )
    else:
        export_mime = None
        data, truncated = _req_bytes(
            f"files/{fid}", {"alt": "media", **_shared_drive_params(True)}, a.max_bytes
        )
    return {
        "ok": True,
        "id": meta.get("id"),
        "name": meta.get("name"),
        "mimeType": mime,
        "exportedAs": export_mime,
        "truncated": truncated,
        "content": data.decode("utf-8", errors="replace"),
    }


def _guess_content_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return (
        _CONTENT_TYPES.get(ext)
        or mimetypes.guess_type(path)[0]
        or "application/octet-stream"
    )


def _upload_cmd(a: argparse.Namespace, file_id: str | None) -> dict[str, Any]:
    """Shared body for `upload` (create) and `replace` (update content)."""
    with open(a.path, "rb") as fh:
        content = fh.read()
    content_type = a.content_type or _guess_content_type(a.path)
    metadata: dict[str, Any] = {}
    if file_id is None:
        metadata["name"] = a.name or os.path.basename(a.path)
        if a.parent:
            metadata["parents"] = [a.parent]
        # Setting a Google-native target mimeType makes Drive convert the upload
        # (e.g. markdown -> a real Google Doc).
        if a.convert_to:
            metadata["mimeType"] = a.convert_to
    file = _upload(metadata, content, content_type, file_id=file_id)
    return {"ok": True, "file": file}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gdrive_api.py", description="Google Drive.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
        sp.add_argument(
            "--shared-drives",
            dest="shared_drives",
            action="store_true",
            help="include items from shared drives, not just My Drive",
        )

    sp = sub.add_parser("search", help="search/list files")
    sp.add_argument("text", nargs="?", help="free-text query (fullText contains)")
    sp.add_argument("--name", help="filter: name contains")
    sp.add_argument("--mime", help="filter: exact mimeType")
    sp.add_argument("--in", dest="parent", help="filter: files in this folder id")
    sp.add_argument(
        "--include-trashed",
        dest="include_trashed",
        action="store_true",
        help="include trashed files (excluded by default)",
    )
    with_common(sp)

    sp = sub.add_parser("list", help="list a folder's children")
    sp.add_argument("folder_id")
    with_common(sp)

    sp = sub.add_parser("get", help="one file's metadata")
    sp.add_argument("file_id")
    sp.add_argument("--fields", default=_FILE_FIELDS, help="Drive fields selector")

    sp = sub.add_parser("read", help="read a file's contents as text")
    sp.add_argument("file_id")
    sp.add_argument("--mime", help="override export mimeType for native docs")
    sp.add_argument(
        "--max-bytes", dest="max_bytes", type=int, default=_DEFAULT_MAX_BYTES
    )

    sp = sub.add_parser("drives", help="list shared drives")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    # --- writes (may prompt for approval) ---
    sp = sub.add_parser("create-folder", help="create a folder (write)")
    sp.add_argument("name")
    sp.add_argument("--in", dest="parent", help="parent folder id")

    sp = sub.add_parser(
        "upload", help="upload a local file as a new Drive file (write)"
    )
    sp.add_argument("path", help="local file path to upload")
    sp.add_argument("--name", help="Drive file name (default: basename)")
    sp.add_argument("--in", dest="parent", help="parent folder id")
    sp.add_argument("--as", dest="content_type", help="source content-type override")
    sp.add_argument(
        "--convert-to",
        dest="convert_to",
        help="target Google-native mimeType, e.g. application/vnd.google-apps.document",
    )

    sp = sub.add_parser("replace", help="replace a file's contents (write)")
    sp.add_argument("file_id")
    sp.add_argument("path", help="local file path with the new contents")
    sp.add_argument("--as", dest="content_type", help="source content-type override")

    sp = sub.add_parser("update", help="update a file's metadata (write)")
    sp.add_argument("file_id")
    sp.add_argument("--name", help="new name")
    sp.add_argument("--add-parent", dest="add_parent", help="folder id to add")
    sp.add_argument("--remove-parent", dest="remove_parent", help="folder id to remove")

    sp = sub.add_parser("trash", help="move a file to the trash (write)")
    sp.add_argument("file_id")

    sp = sub.add_parser("delete", help="permanently delete a file (destructive)")
    sp.add_argument("file_id")

    sp = sub.add_parser("call", help="raw Drive request")
    sp.add_argument("method", choices=("GET", "POST", "PATCH", "PUT", "DELETE"))
    sp.add_argument("path", help="appended to drive/v3/")
    sp.add_argument("json_body", nargs="?", help="JSON object for the request body")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "search":
        return _list(_build_query(a), a)

    if a.cmd == "list":
        a.parent = a.folder_id
        a.include_trashed = False
        return _list(_build_query(a), a)

    if a.cmd == "get":
        meta = _req_json(
            f"files/{_seg(a.file_id)}",
            {"fields": a.fields, **_shared_drive_params(True)},
        )
        return {"ok": True, "file": meta}

    if a.cmd == "read":
        return _read(a)

    if a.cmd == "drives":
        return _paginate("drives", "drives", {}, a.limit)

    if a.cmd == "create-folder":
        body: dict[str, Any] = {"name": a.name, "mimeType": _FOLDER_MIME}
        if a.parent:
            body["parents"] = [a.parent]
        file = _req_json(
            "files",
            {"fields": _FILE_FIELDS, "supportsAllDrives": "true"},
            method="POST",
            body=body,
        )
        return {"ok": True, "file": file}

    if a.cmd == "upload":
        return _upload_cmd(a, file_id=None)

    if a.cmd == "replace":
        return _upload_cmd(a, file_id=a.file_id)

    if a.cmd == "update":
        body = {}
        if a.name:
            body["name"] = a.name
        params: dict[str, Any] = {
            "fields": _FILE_FIELDS,
            "supportsAllDrives": "true",
            "addParents": a.add_parent,
            "removeParents": a.remove_parent,
        }
        file = _req_json(f"files/{_seg(a.file_id)}", params, method="PATCH", body=body)
        return {"ok": True, "file": file}

    if a.cmd == "trash":
        file = _req_json(
            f"files/{_seg(a.file_id)}",
            {"fields": "id,name,trashed", "supportsAllDrives": "true"},
            method="PATCH",
            body={"trashed": True},
        )
        return {"ok": True, "file": file}

    if a.cmd == "delete":
        _req_json(
            f"files/{_seg(a.file_id)}",
            {"supportsAllDrives": "true"},
            method="DELETE",
        )
        return {"ok": True, "deleted": True}

    # `call` raw escape hatch
    parsed_body = None
    if a.json_body:
        try:
            parsed_body = json.loads(a.json_body)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"invalid json_body: {e}"}
        if not isinstance(parsed_body, dict):
            return {"ok": False, "error": "json_body_not_object"}
    resp = _req_json(a.path.lstrip("/"), method=a.method, body=parsed_body)
    return {"ok": True, "data": resp}


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except FileNotFoundError as e:
        print(f"file not found: {e.filename}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"Google Drive returned a non-JSON response: {e}", file=sys.stderr)
        return 1
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} calling Google Drive: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling Google Drive: {e.reason}", file=sys.stderr)
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
