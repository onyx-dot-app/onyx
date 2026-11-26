"""Endpoint lines: a view of an OpenAPI document with one line per operation,
``METHOD /path?query1&query2 Name``. Applying lines edits the document: an
operation whose line did not change stays as it was."""

import copy
import hashlib
import json
import re
from typing import Any

import yaml
from pydantic import BaseModel

from onyx.tools.tool_implementations.custom.openapi_parsing import (
    OPENAPI_METHODS,
    check_unique_name,
    openapi_operations,
    openapi_to_method_spec,
    operation_parameters,
    parse_openapi_document,
    resolve_ref,
)

_LINE_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_PATH_PARAM = re.compile(r"\{([^{}]*)\}")
_PARAM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")
_QUERY_NAME = re.compile(r"[^\s&?=#]+")


class EndpointLineError(BaseModel):
    # The index of the line in the request.
    line: int
    message: str


class EndpointLinesError(ValueError):
    def __init__(self, errors: list[EndpointLineError]) -> None:
        super().__init__(
            "; ".join(f"Line {error.line + 1}: {error.message}" for error in errors)
        )
        self.errors = errors


def _line_name(operation: dict[str, Any]) -> str:
    return " ".join(
        str(operation.get("summary") or operation.get("description") or "").split()
    )


def _is_query(param: Any) -> bool:
    return (
        isinstance(param, dict)
        and param.get("in") == "query"
        and isinstance(param.get("name"), str)
    )


def _query_names(
    spec: dict[str, Any], path_item: dict[str, Any], operation: dict[str, Any]
) -> list[str]:
    """The query parameters of the operation, with the ones of its path item
    and with references resolved."""
    return [
        param["name"]
        for param in operation_parameters(spec, path_item, operation)
        if _is_query(param)
    ]


def _path_item(spec: dict[str, Any], path: str) -> dict[str, Any]:
    paths = spec.get("paths")
    item = paths.get(path) if isinstance(paths, dict) else None
    return item if isinstance(item, dict) else {}


def _string_param(name: str, location: str) -> dict[str, Any]:
    return {
        "name": name,
        "in": location,
        "required": location == "path",
        "schema": {"type": "string"},
    }


def _operations(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(method).upper(), path): operation
        for path, _, method, operation in openapi_operations(spec)
        if str(method).upper() in _LINE_METHODS
    }


def _new_operation_id(method: str, path: str) -> str:
    """Readable, with a hash of the exact method and path: ``/a-b`` and
    ``/a_b`` get different keys, so a new endpoint never takes the key, and so
    the stored policies, of another one."""
    readable = re.sub(r"[^a-z0-9]+", "_", f"{method}_{path}".lower()).strip("_")
    digest = hashlib.sha256(f"{method} {path}".encode()).hexdigest()[:8]
    return f"{readable}_{digest}"


def _remove_operation(paths: dict[str, Any], path: str, method_key: str) -> None:
    """Remove one operation, then its path if no operation is left."""
    item = paths[path]
    del item[method_key]
    if not any(str(key).lower() in OPENAPI_METHODS for key in item):
        del paths[path]


def _endpoint_line(
    spec: dict[str, Any], method: str, path: str, operation: dict[str, Any]
) -> str:
    query = _query_names(spec, _path_item(spec, path), operation)
    query_text = f"?{'&'.join(query)}" if query else ""
    return f"{method} {path}{query_text} {_line_name(operation)}"


def endpoint_lines(spec: dict[str, Any]) -> list[str]:
    return [
        _endpoint_line(spec, method, path, operation)
        for (method, path), operation in _operations(spec).items()
    ]


def _parse_line(text: str) -> tuple[str, str, list[str], str]:
    parts = text.split(maxsplit=2)
    method = parts[0].upper() if parts else ""
    if method not in _LINE_METHODS:
        raise ValueError(f"Start the line with one of {', '.join(_LINE_METHODS)}.")
    if len(parts) < 2 or not parts[1].startswith("/"):
        raise ValueError("Put a path that starts with / after the method.")
    if len(parts) < 3:
        raise ValueError("Put a name after the path.")
    path, _, query_text = parts[1].partition("?")
    if "#" in path:
        raise ValueError("The path must not have a #. Write %23 for a # in a path.")
    unpaired = _PATH_PARAM.sub("", path)
    if "{" in unpaired or "}" in unpaired:
        raise ValueError("Each { in the path needs a matching }.")
    path_params = _PATH_PARAM.findall(path)
    for param in path_params:
        if not _PARAM_NAME.fullmatch(param):
            raise ValueError(f"'{{{param}}}' is not a valid path parameter.")
    query = query_text.split("&") if query_text else []
    for name in query:
        if not _QUERY_NAME.fullmatch(name):
            raise ValueError(
                f"'{name}' is not a valid query parameter. Write ?a&b, with no values."
            )
    if len(set(path_params)) != len(path_params) or len(set(query)) != len(query):
        raise ValueError("Each parameter needs a different name.")
    return method, path, query, parts[2].strip()


def _operation(
    spec: dict[str, Any],
    method: str,
    path: str,
    query: list[str],
    name: str,
    old: dict[str, Any] | None,
) -> dict[str, Any]:
    """A new minimal operation, or ``old`` with the name and query of the
    line. A parameter that the spec defines keeps its definition. Raises
    ``ValueError`` when the line leaves out a query parameter of the path
    item."""
    path_item = _path_item(spec, path)
    old_query = None if old is None else _query_names(spec, path_item, old)
    if query != old_query:
        for inherited in _query_names(spec, path_item, {}):
            if inherited not in query:
                raise ValueError(
                    f"Each operation of {path} has ?{inherited}. "
                    "Remove it from the path in the spec."
                )
    if old is None:
        defined = {
            (param.get("name"), param.get("in"))
            for param in operation_parameters(spec, path_item, {})
            if isinstance(param, dict)
        }
        params = [
            _string_param(p, "path")
            for p in _PATH_PARAM.findall(path)
            if (p, "path") not in defined
        ]
        params += [
            _string_param(q, "query") for q in query if (q, "query") not in defined
        ]
        operation: dict[str, Any] = {
            "operationId": _new_operation_id(method, path),
            "summary": name,
        }
        if params:
            operation["parameters"] = params
        if method in ("POST", "PUT", "PATCH"):
            operation["requestBody"] = {
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "additionalProperties": True}
                    }
                }
            }
        operation["responses"] = {"200": {"description": "Success"}}
        return operation
    operation = copy.deepcopy(old)
    if name != _line_name(old):
        operation["summary"] = name
    if old_query is not None and query != old_query:
        params = [
            param
            for param in operation.get("parameters") or []
            if not (
                _is_query(resolved := resolve_ref(spec, param))
                and resolved["name"] not in query
            )
        ]
        params += [_string_param(q, "query") for q in query if q not in old_query]
        operation["parameters"] = params
        if not params:
            del operation["parameters"]
    return operation


def apply_endpoint_lines(
    document: str | None,
    *,
    title: str,
    description: str | None,
    base_url: str,
    lines: list[str],
) -> str:
    """Apply ``lines`` and ``base_url`` to ``document``, or to a new document
    when it is None. YAML stays YAML. Raises ``EndpointLinesError`` with the
    errors of each line, and ``ValueError`` for a document that is not JSON or
    YAML."""
    original: dict[str, Any] = (
        parse_openapi_document(document)
        if document is not None
        else {
            "openapi": "3.0.3",
            "info": {
                "title": title,
                "description": description or title,
                "version": "1.0.0",
            },
            "paths": {},
        }
    )
    spec = copy.deepcopy(original)
    existing = _operations(spec)
    errors: list[EndpointLineError] = []
    wanted: dict[tuple[str, str], dict[str, Any]] = {}
    new_lines: dict[tuple[str, str], int] = {}
    for index, text in enumerate(lines):
        if not text.strip():
            continue
        try:
            method, path, query, name = _parse_line(text)
            key = (method, path)
            if key in wanted:
                raise ValueError(f"Another line already has {method} {path}.")
            spec_paths = spec.get("paths")
            if isinstance(spec_paths, dict) and not isinstance(
                spec_paths.get(path, {}), dict
            ):
                raise ValueError(f"{path} in the spec is not an object.")
            old = existing.get(key)
            wanted[key] = _operation(spec, method, path, query, name, old)
        except ValueError as e:
            errors.append(EndpointLineError(line=index, message=str(e)))
            continue
        if old is None:
            new_lines[key] = index
    # A removed operation's key keeps its stored policies, so a new endpoint
    # must not take it.
    stored_ids = {
        operation_id
        for *_, operation in openapi_operations(original)
        if isinstance(operation_id := operation.get("operationId"), str)
    }
    for key, index in new_lines.items():
        new_id = wanted[key]["operationId"]
        if new_id in stored_ids or any(
            other_key != key and other.get("operationId") == new_id
            for other_key, other in wanted.items()
        ):
            errors.append(
                EndpointLineError(
                    line=index,
                    message=f"Another endpoint already has the action key {new_id}.",
                )
            )
    if errors:
        raise EndpointLinesError(sorted(errors, key=lambda error: error.line))

    if not isinstance(spec.get("paths"), dict):
        spec["paths"] = {}
    paths: dict[str, Any] = spec["paths"]
    # Install first: a removal that empties a path drops the parameters of
    # its path item, which a replacing operation can need.
    for (method, path), operation in wanted.items():
        item = paths.setdefault(path, {})
        stored_key = next((key for key in item if str(key).upper() == method), None)
        item[stored_key or method.lower()] = operation
    for method, path in existing:
        if (method, path) not in wanted:
            method_key = next(key for key in paths[path] if str(key).upper() == method)
            _remove_operation(paths, path, method_key)
    servers = spec.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        # A tool calls one server: the base URL replaces the others.
        spec["servers"] = [{**servers[0], "url": base_url}]
    else:
        spec["servers"] = [{"url": base_url}]

    if document is None:
        return json.dumps(spec, indent=2)
    if spec == original:
        return document
    return _dump_like(document, spec)


def _dump_like(document: str, spec: dict[str, Any]) -> str:
    """``spec`` as JSON if ``document`` is JSON, else as YAML."""
    try:
        json.loads(document)
    except json.JSONDecodeError:
        return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)
    return json.dumps(spec, indent=2)


def _check_line_round_trip(
    spec: dict[str, Any], method: str, path: str, operation: dict[str, Any]
) -> None:
    """Add sends the imported lines back, so each line must read back as the
    same path and query names."""
    query = _query_names(spec, _path_item(spec, path), operation)
    _, parsed_path, parsed_query, _ = _parse_line(
        _endpoint_line(spec, method, path, operation)
    )
    if parsed_path != path or parsed_query != query:
        bad = [name for name in query if not _QUERY_NAME.fullmatch(name)]
        raise ValueError(
            f"'{bad[0]}' cannot be written in an endpoint line."
            if bad
            else f"'{path}' cannot be written in an endpoint line."
        )


def drop_uncallable_operations(
    document: str, spec: dict[str, Any]
) -> tuple[str, list[str]]:
    """Drop from ``spec``, the parsed ``document``, the operations that no
    tool can call. Returns the document text without them, and one
    ``METHOD /path: reason`` line for each operation it dropped. With nothing
    to drop, the text stays as it was."""
    skipped: list[str] = []
    seen_names: dict[str, str] = {}
    for path, path_item, method, operation in openapi_operations(spec):
        try:
            method_spec = openapi_to_method_spec(
                spec, path, path_item, method, operation
            )
            method_spec.validate_spec()
            if str(method).upper() in _LINE_METHODS:
                _check_line_round_trip(spec, str(method).upper(), path, operation)
            check_unique_name(method_spec, seen_names)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            skipped.append(f"{str(method).upper()} {path}: {e}")
            _remove_operation(spec["paths"], path, method)
    if not skipped:
        return document, []
    return _dump_like(document, spec), skipped
