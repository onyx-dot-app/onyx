"""Derive Craft gateway configuration from an OpenAPI action."""

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import CatalogAction, RestRoute
from onyx.external_apps.url_glob import UrlGlob
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    MethodSpec,
    openapi_to_method_specs,
    openapi_to_url,
)
from onyx.utils.headers import HeaderItemDict, is_valid_header_name
from onyx.utils.url import normalized_request_path


def _parse_openapi_action(
    definition: dict[str, Any],
) -> tuple[str, list[MethodSpec]]:
    """Validate the shared server and operations, returning their parsed values."""
    try:
        value = openapi_to_url(definition)
        methods = openapi_to_method_specs(definition)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(error)) from error
    if any("servers" in method.spec for method in methods):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Craft does not support operation-level server overrides. Use the schema's root server URL.",
        )
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Invalid OpenAPI server URL."
        ) from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(character in value for character in "*{}\\\r\n\t ")
        or normalized_request_path(parsed.path or "/")
        != (parsed.path.rstrip("/") or "/")
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Craft requires an absolute HTTP or HTTPS server URL with a literal host and base path, without variables, credentials, queries, or fragments.",
        )
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    if port is not None and (parsed.scheme, port) not in {("http", 80), ("https", 443)}:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", "")), methods


def openapi_url_patterns(definition: dict[str, Any]) -> list[str]:
    """Use the same server as the chat action, scoped to its base path."""
    base, _ = _parse_openapi_action(definition)
    if not urlsplit(base).path:
        base += "/"
    return sorted(
        {
            UrlGlob.parse(pattern).value
            for pattern in (base, f"{base}?*", f"{base.rstrip('/')}/*")
        }
    )


def openapi_action_catalog(definition: dict[str, Any]) -> list[CatalogAction]:
    """Bind each policy to its destination and route, independent of operation names."""
    base, operations = _parse_openapi_action(definition)
    base_path = urlsplit(base).path
    actions: list[CatalogAction] = []
    for operation in operations:
        path = operation.path
        if (
            not path.startswith("/")
            or normalized_request_path(path) != (path.rstrip("/") or "/")
            or any(character in path for character in "?#\\")
            or "...}" in path
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Craft requires canonical OpenAPI paths without queries, fragments, or wildcard parameters.",
            )
        method = operation.method.upper()
        actions.append(
            CatalogAction(
                id=f"{method} {base}{path}",
                normalised_name=operation.raw_name,
                description=operation.summary,
                matches=(RestRoute(method=method, path=f"{base_path}{path}"),),
                method=method,
                path=path,
            )
        )
    return actions


def openapi_auth_configuration(
    headers: list[HeaderItemDict] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Keep secrets in encrypted credentials, including values with braces."""
    template: dict[str, str] = {}
    credentials: dict[str, str] = {}
    seen: set[str] = set()
    for index, header in enumerate(headers or []):
        name, value = header["key"], header["value"]
        if (
            not is_valid_header_name(name)
            or name.lower() in seen
            or "\r" in value
            or "\n" in value
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Craft requires valid, unique HTTP headers.",
            )
        seen.add(name.lower())
        key = f"header_{index}"
        template[name] = "{" + key + "}"
        credentials[key] = value
    return template, credentials
