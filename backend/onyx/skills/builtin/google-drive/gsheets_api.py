#!/usr/bin/env python3
"""Google Sheets wrapper for the Onyx Craft sandbox.

Common operations exposed as subcommands. Output is JSON on stdout. No auth is
handled here: the sandbox egress proxy injects the connected user's bearer token.
Writes (create / update / append / clear / batch-update) may pause for user
approval at the proxy.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://sheets.googleapis.com/v4/"
_HTTP_TIMEOUT_SECONDS = 180
# Compact structure view: enough to find sheets and their sizes without the
# full per-cell grid data.
_DEFAULT_GET_FIELDS = (
    "spreadsheetId,spreadsheetUrl,properties(title,locale,timeZone),"
    "sheets(properties(sheetId,title,index,gridProperties(rowCount,columnCount)))"
)


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
    """URL-encode a single path segment (ids and A1 ranges may contain special
    chars)."""
    return urllib.parse.quote(value, safe="")


def _req_json(
    path: str,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a Sheets endpoint; return parsed JSON ({} on empty/204)."""
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


def _values_body(a: argparse.Namespace) -> dict[str, Any]:
    values = _load_json_arg(a.values_json, a.values_file, "values")
    if not isinstance(values, list) or not all(isinstance(r, list) for r in values):
        raise ValueError("values must be a JSON array of row arrays, e.g. [[1,2]]")
    return {"values": values}


def _input_option(a: argparse.Namespace) -> str:
    # USER_ENTERED parses input like typing in the UI (numbers, dates, =SUM()).
    return "RAW" if a.raw_input else "USER_ENTERED"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gsheets_api.py", description="Google Sheets.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("get", help="a spreadsheet's structure (sheets + sizes)")
    sp.add_argument("spreadsheet_id")
    sp.add_argument(
        "--fields",
        default=_DEFAULT_GET_FIELDS,
        help="Sheets fields selector (default: compact structure view)",
    )

    sp = sub.add_parser("values", help="read cell values from an A1 range")
    sp.add_argument("spreadsheet_id")
    sp.add_argument("range", help="A1 notation, e.g. 'Sheet1!A1:C10' or 'Sheet1'")
    sp.add_argument(
        "--formulas",
        action="store_true",
        help="return cell formulas instead of computed values",
    )

    sp = sub.add_parser("create", help="create a new spreadsheet (write)")
    sp.add_argument("--title", required=True, help="title of the new spreadsheet")
    sp.add_argument(
        "--sheet",
        dest="sheets",
        action="append",
        help="add a sheet (tab) with this title; repeatable",
    )

    def values_write(name: str, help_text: str) -> argparse.ArgumentParser:
        wp = sub.add_parser(name, help=help_text)
        wp.add_argument("spreadsheet_id")
        wp.add_argument("range", help="A1 notation target range")
        wp.add_argument(
            "values_json", nargs="?", help="JSON array of row arrays, e.g. [[1,2]]"
        )
        wp.add_argument(
            "--file",
            dest="values_file",
            help="path to a file holding the JSON values array (instead of inline)",
        )
        wp.add_argument(
            "--raw-input",
            dest="raw_input",
            action="store_true",
            help="store input verbatim instead of parsing like UI entry",
        )
        return wp

    values_write("update-values", "overwrite cell values in a range (write)")
    values_write("append-values", "append rows after a table's last row (write)")

    sp = sub.add_parser("clear-values", help="clear cell values in a range (write)")
    sp.add_argument("spreadsheet_id")
    sp.add_argument("range", help="A1 notation range to clear")

    sp = sub.add_parser(
        "batch-update",
        help="apply raw Sheets batchUpdate requests (write)",
    )
    sp.add_argument("spreadsheet_id")
    sp.add_argument(
        "requests_json",
        nargs="?",
        help="JSON array of Sheets request objects (e.g. addSheet, "
        "updateCells, repeatCell, mergeCells, deleteRange)",
    )
    sp.add_argument(
        "--file",
        dest="requests_file",
        help="path to a file holding the JSON requests array (instead of inline)",
    )
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "get":
        data = _req_json(f"spreadsheets/{_seg(a.spreadsheet_id)}", {"fields": a.fields})
        return {"ok": True, "spreadsheet": data}

    if a.cmd == "values":
        params = {"valueRenderOption": "FORMULA"} if a.formulas else None
        data = _req_json(
            f"spreadsheets/{_seg(a.spreadsheet_id)}/values/{_seg(a.range)}", params
        )
        return {"ok": True, "data": data}

    if a.cmd == "create":
        body: dict[str, Any] = {"properties": {"title": a.title}}
        if a.sheets:
            body["sheets"] = [{"properties": {"title": t}} for t in a.sheets]
        data = _req_json(
            "spreadsheets",
            {"fields": _DEFAULT_GET_FIELDS},
            method="POST",
            body=body,
        )
        return {"ok": True, "spreadsheet": data}

    if a.cmd == "update-values":
        data = _req_json(
            f"spreadsheets/{_seg(a.spreadsheet_id)}/values/{_seg(a.range)}",
            {"valueInputOption": _input_option(a)},
            method="PUT",
            body=_values_body(a),
        )
        return {"ok": True, "data": data}

    if a.cmd == "append-values":
        data = _req_json(
            f"spreadsheets/{_seg(a.spreadsheet_id)}/values/{_seg(a.range)}:append",
            {"valueInputOption": _input_option(a)},
            method="POST",
            body=_values_body(a),
        )
        return {"ok": True, "data": data}

    if a.cmd == "clear-values":
        data = _req_json(
            f"spreadsheets/{_seg(a.spreadsheet_id)}/values/{_seg(a.range)}:clear",
            method="POST",
            body={},
        )
        return {"ok": True, "data": data}

    # batch-update
    requests = _load_json_arg(a.requests_json, a.requests_file, "requests")
    if not isinstance(requests, list):
        raise ValueError("requests must be a JSON array of request objects")
    data = _req_json(
        f"spreadsheets/{_seg(a.spreadsheet_id)}:batchUpdate",
        method="POST",
        body={"requests": requests},
    )
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
        print(f"HTTP {e.code} calling Google Sheets: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling Google Sheets: {e.reason}", file=sys.stderr)
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
