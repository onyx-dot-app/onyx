#!/usr/bin/env python3
"""Google Slides wrapper for the Onyx Craft sandbox.

Common operations exposed as subcommands. Output is JSON on stdout. No auth is
handled here: the sandbox egress proxy injects the connected user's bearer token.
Writes (create / add-slide / text edits / batch-update) may pause for user
approval at the proxy.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://slides.googleapis.com/v1/"
_HTTP_TIMEOUT_SECONDS = 180
# Compact structure view: object ids, element kinds, and text content — enough
# to target edits without the full styling/transform payload.
_DEFAULT_GET_FIELDS = (
    "presentationId,title,revisionId,"
    "slides(objectId,pageElements(objectId,title,"
    "shape(shapeType,placeholder(type,index),"
    "text(textElements(textRun(content)))),"
    "table(rows,columns),image(contentUrl)))"
)
# For plain-text extraction: full pageElements, because grouped elements nest
# arbitrarily deep and the fields syntax can't express that recursion. Only
# the extracted text is emitted, so the larger payload never reaches the LLM.
_TEXT_FIELDS = "title,slides(objectId,pageElements)"


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


def _req_json(
    path: str,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a Slides endpoint; return parsed JSON ({} on empty/204)."""
    url = _BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url += "?" + urllib.parse.urlencode(clean)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"} if data else {}
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        url, data=data, method=method, headers=headers
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _batch_update(presentation_id: str, requests: list[Any]) -> dict[str, Any]:
    """POST a Slides `batchUpdate` with the given list of request objects."""
    return _req_json(
        f"presentations/{_seg(presentation_id)}:batchUpdate",
        method="POST",
        body={"requests": requests},
    )


def _text_runs(text: dict[str, Any]) -> str:
    return "".join(
        element.get("textRun", {}).get("content", "")
        for element in text.get("textElements", [])
    )


def _element_text(element: dict[str, Any]) -> str:
    """Plain text of one page element: shape text, table cell text, and
    grouped children (recursive)."""
    parts: list[str] = []
    shape_text = element.get("shape", {}).get("text")
    if shape_text:
        parts.append(_text_runs(shape_text))
    for row in element.get("table", {}).get("tableRows", []):
        for cell in row.get("tableCells", []):
            if cell.get("text"):
                parts.append(_text_runs(cell["text"]))
    for child in element.get("elementGroup", {}).get("children", []):
        parts.append(_element_text(child))
    return "".join(parts)


def _load_json_arg(inline: str | None, file_path: str | None, what: str) -> Any:
    """A JSON payload given inline or via --file (exactly one required)."""
    if inline is not None and file_path is not None:
        raise ValueError(f"pass {what} inline or via --file, not both")
    raw = inline
    if file_path:
        with open(file_path, encoding="utf-8") as fh:
            raw = fh.read()
    if not raw:
        raise ValueError(f"no {what} given (pass inline JSON or --file)")
    return json.loads(raw)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gslides_api.py", description="Google Slides.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "get", help="a presentation's structure (slides, element ids, text)"
    )
    sp.add_argument("presentation_id")
    sp.add_argument(
        "--fields",
        default=_DEFAULT_GET_FIELDS,
        help="Slides fields selector (default: compact structure view; "
        "pass '' for the whole presentation)",
    )

    sp = sub.add_parser("text", help="plain text of every slide")
    sp.add_argument("presentation_id")

    sp = sub.add_parser("page", help="one page's full structure")
    sp.add_argument("presentation_id")
    sp.add_argument("page_object_id")
    sp.add_argument("--fields", help="Slides fields selector (default: whole page)")

    sp = sub.add_parser("create", help="create a new presentation (write)")
    sp.add_argument("--title", required=True, help="title of the new presentation")

    sp = sub.add_parser("add-slide", help="append a slide (write)")
    sp.add_argument("presentation_id")
    sp.add_argument(
        "--layout",
        default="BLANK",
        help="predefined layout, e.g. BLANK, TITLE, TITLE_AND_BODY, "
        "SECTION_HEADER (default: BLANK)",
    )

    sp = sub.add_parser("insert-text", help="insert text into a shape (write)")
    sp.add_argument("presentation_id")
    sp.add_argument("object_id", help="target shape objectId (see `get`)")
    sp.add_argument("--text", required=True, help="text to insert")
    sp.add_argument("--index", type=int, default=0, help="character index to insert at")

    sp = sub.add_parser(
        "replace-text", help="replace all occurrences of a string (write)"
    )
    sp.add_argument("presentation_id")
    sp.add_argument("--find", required=True, help="text to find")
    sp.add_argument("--replace", required=True, help="replacement text")
    sp.add_argument(
        "--match-case",
        dest="match_case",
        action="store_true",
        help="case-sensitive matching (case-insensitive by default)",
    )

    sp = sub.add_parser(
        "batch-update",
        help="apply raw Slides batchUpdate requests (write)",
    )
    sp.add_argument("presentation_id")
    sp.add_argument(
        "requests_json",
        nargs="?",
        help="JSON array of Slides request objects (e.g. createSlide, "
        "createShape, insertText, updateTextStyle, deleteObject)",
    )
    sp.add_argument(
        "--file",
        dest="requests_file",
        help="path to a file holding the JSON requests array (instead of inline)",
    )
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "get":
        params = {"fields": a.fields} if a.fields else None
        data = _req_json(f"presentations/{_seg(a.presentation_id)}", params)
        return {"ok": True, "presentation": data}

    if a.cmd == "text":
        data = _req_json(
            f"presentations/{_seg(a.presentation_id)}",
            {"fields": _TEXT_FIELDS},
        )
        slides = [
            {
                "index": i,
                "objectId": slide.get("objectId"),
                "text": "".join(
                    _element_text(el) for el in slide.get("pageElements", [])
                ),
            }
            for i, slide in enumerate(data.get("slides", []))
        ]
        return {"ok": True, "title": data.get("title"), "slides": slides}

    if a.cmd == "page":
        params = {"fields": a.fields} if a.fields else None
        data = _req_json(
            f"presentations/{_seg(a.presentation_id)}/pages/{_seg(a.page_object_id)}",
            params,
        )
        return {"ok": True, "page": data}

    if a.cmd == "create":
        data = _req_json("presentations", method="POST", body={"title": a.title})
        return {"ok": True, "presentation": data}

    if a.cmd == "add-slide":
        requests = [
            {"createSlide": {"slideLayoutReference": {"predefinedLayout": a.layout}}}
        ]
        data = _batch_update(a.presentation_id, requests)
        replies = data.get("replies") or [{}]
        object_id = replies[0].get("createSlide", {}).get("objectId")
        return {"ok": True, "objectId": object_id, "data": data}

    if a.cmd == "insert-text":
        requests = [
            {
                "insertText": {
                    "objectId": a.object_id,
                    "insertionIndex": a.index,
                    "text": a.text,
                }
            }
        ]
        data = _batch_update(a.presentation_id, requests)
        return {"ok": True, "data": data}

    if a.cmd == "replace-text":
        requests = [
            {
                "replaceAllText": {
                    "containsText": {
                        "text": a.find,
                        "matchCase": a.match_case,
                    },
                    "replaceText": a.replace,
                }
            }
        ]
        data = _batch_update(a.presentation_id, requests)
        return {"ok": True, "data": data}

    # batch-update
    requests = _load_json_arg(a.requests_json, a.requests_file, "requests")
    if not isinstance(requests, list):
        raise ValueError("requests must be a JSON array of request objects")
    data = _batch_update(a.presentation_id, requests)
    return {"ok": True, "data": data}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except FileNotFoundError as e:
        print(f"file not found: {e.filename}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"invalid JSON: {e}", file=sys.stderr)
        return 1
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} calling Google Slides: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling Google Slides: {e.reason}", file=sys.stderr)
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
