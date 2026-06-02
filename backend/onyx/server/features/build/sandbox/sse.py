"""SSE marker types. Lives in a leaf module so base.py and the opencode
package don't form a circular import."""

from dataclasses import dataclass


@dataclass
class SSEKeepalive:
    """Marker yielded when no real sandbox events arrive within the keepalive
    window. Defined once so isinstance checks in the session-manager pipeline
    work uniformly across backends."""
