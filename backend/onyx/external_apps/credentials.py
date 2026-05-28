"""Render an external app's outbound auth headers from its template.

The egress proxy injects credentials into verified requests by filling the
``auth_template``'s ``{placeholder}`` fields from the app's resolved credentials
(org + per-user). Kept pure so the substitution rules are testable without a DB;
the caller (``onyx.db.external_app.resolve_injection_headers``) resolves the
credentials.
"""

from typing import Any


def build_auth_headers(
    auth_template: dict[str, Any],
    credentials: dict[str, Any],
) -> dict[str, str]:
    """Fill each ``auth_template`` header value's ``{placeholder}`` fields from
    ``credentials``, returning ``{header_name: rendered_value}``.

    A header whose template references a credential not present in
    ``credentials`` is **omitted** — the request goes out without that header
    rather than with a half-filled secret. ``str.format`` substitutes values
    once (it does not re-interpret braces inside the substituted values), so a
    credential value containing ``{`` is safe.
    """
    headers: dict[str, str] = {}
    for name, template in auth_template.items():
        if not isinstance(template, str):
            continue
        try:
            headers[name] = template.format(**credentials)
        except (KeyError, IndexError, ValueError, AttributeError, TypeError):
            # Render failed for this header
            continue
    return headers
