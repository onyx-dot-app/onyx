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

from mitmproxy import http

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.external_app import get_external_apps
from onyx.db.models import ExternalApp
from onyx.external_apps.matching.engine import match_action
from onyx.external_apps.matching.engine import RequestMatch
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ActionMatcher(Protocol):
    def match(self, request: http.Request, tenant_id: str) -> RequestMatch | None: ...


def resolve_app_for_url(
    url: str,
    apps: Iterable[ExternalApp],
) -> ExternalApp | None:
    """Return the first ``app`` whose any ``upstream_url_patterns`` entry matches
    ``url``, or ``None`` if no connected app claims it.

    ``apps`` is expected id-ordered (as ``get_external_apps`` returns it), so the
    lowest-id app wins when patterns overlap. A malformed stored pattern is
    skipped rather than failing the whole resolution — egress for other apps must
    not hinge on one bad regex.
    """
    for app in apps:
        for pattern in app.upstream_url_patterns:
            try:
                if re.fullmatch(pattern, url):
                    return app
            except re.error:
                logger.warning(
                    "skipping malformed upstream_url_pattern app_id=%s pattern=%r",
                    app.id,
                    pattern,
                )
    return None


class ExternalAppActionMatcher(ActionMatcher):
    """Matches a request against the tenant's connected external apps.

    Opens its own short tenant-scoped DB session (mirrors ``IdentityResolver``):
    load the tenant's apps, resolve the one owning the request URL, then defer to
    the pre-written ``match_action`` for the policy verdict.
    """

    def match(self, request: http.Request, tenant_id: str) -> RequestMatch | None:
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
            matched = match_action(db, app, proxied)
            if matched is None:
                return None

        # Engine leaves `payload` empty — we own the raw content + content-type.
        payload = _decode_body(
            request.raw_content or b"",
            (request.headers.get("content-type") or "").lower(),
        )
        return matched.model_copy(update={"payload": payload or {}})


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
