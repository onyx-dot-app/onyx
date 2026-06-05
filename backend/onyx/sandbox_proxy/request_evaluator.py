"""Classify an intercepted HTTPS request into a gated action.

The gate addon treats both a `None` return and any matcher exception as
"not gated" — the real security boundary is the proxy's iptables egress
lockdown, not this heuristic.
"""

import json
import re
from collections.abc import Iterable
from typing import Any
from typing import Protocol
from urllib.parse import parse_qs
from uuid import UUID

from mitmproxy import http

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.external_app import get_external_apps
from onyx.db.models import ExternalApp
from onyx.external_apps.credentials import app_is_available
from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.external_apps.matching.engine import apply_credential_gate
from onyx.external_apps.matching.engine import recognize_actions
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()


class RequestEvaluator(Protocol):
    def evaluate(
        self, request: http.Request, tenant_id: str, user_id: UUID
    ) -> AllMatchedActions | None: ...


def resolve_app_for_url(
    url: str,
    apps: Iterable[ExternalApp],
) -> ExternalApp | None:
    """Return the first ``app`` whose any ``upstream_url_patterns`` entry matches
    ``url``, or ``None`` if no connected app claims it.

    ``apps`` is expected id-ordered (as ``get_external_apps`` returns it), so the
    lowest-id app wins when patterns overlap. A malformed built-in regex is
    skipped rather than failing resolution for every other app.
    """
    for app in apps:
        for regex in app.upstream_url_regexes:
            try:
                if re.fullmatch(regex, url):
                    return app
            except re.error:
                logger.warning(
                    "skipping malformed upstream_url_pattern app_id=%s pattern=%r",
                    app.id,
                    regex,
                )
    return None


class ExternalAppRequestEvaluator(RequestEvaluator):
    """Matches a request against the tenant's connected external apps.

    Opens its own short tenant-scoped DB session (mirrors ``IdentityResolver``):
    load the tenant's apps, resolve the one owning the request URL, recognise the
    catalog action(s) via ``recognize_actions``, then apply the credential gate via
    ``apply_credential_gate`` to produce the verdict.
    """

    def evaluate(
        self, request: http.Request, tenant_id: str, user_id: UUID
    ) -> AllMatchedActions | None:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            apps = get_external_apps(db)
            app = resolve_app_for_url(request.url, apps)
            if app is None:
                return None

            # Catalog path matchers test the URL path only; mitmproxy's
            # `request.path` carries the query string, so drop it.
            proxied = ProxiedRequest(
                method=request.method or "",
                path=(request.path or "").split("?", 1)[0],
                body=request.raw_content,
            )
            matched_actions = apply_credential_gate(
                app,
                proxied,
                recognize_actions(db, app, proxied),
                is_available=app_is_available(db, app, user_id),
            )
            if matched_actions is None:
                return None

        # Engine leaves `payload` empty — we own the raw content + content-type.
        payload = _decode_body(
            request.raw_content or b"",
            (request.headers.get("content-type") or "").lower(),
        )
        return matched_actions.model_copy(update={"payload": payload or {}})


def _decode_body(body: bytes, content_type: str) -> dict[str, Any] | None:
    if "application/json" in content_type:
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(decoded, dict):
            return decoded
        # A batched GraphQL POST (the canonical multi-action case) is a JSON
        # array at the top level. Wrap so the FE's dict-keyed payload view
        # still surfaces the queries.
        if isinstance(decoded, list):
            return {"batch": decoded}
        return None

    if "application/x-www-form-urlencoded" in content_type:
        try:
            raw = parse_qs(body.decode("utf-8"))
        except UnicodeDecodeError:
            return None
        # Collapse parse_qs's list-per-key to match the JSON shape.
        return {
            key: (values[0] if len(values) == 1 else values)
            for key, values in raw.items()
        }

    return None
