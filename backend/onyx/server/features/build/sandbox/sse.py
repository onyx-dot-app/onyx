"""Marker types yielded by sandbox-manager ACP clients.

Lives in its own module so that ``base.py`` can import the opencode
package (which transitively imports this marker via ``serve_client.py``)
without forming a circular import.
"""

from dataclasses import dataclass


@dataclass
class SSEKeepalive:
    """Marker event yielded by sandbox-manager ACP clients when no real ACP
    events have arrived for ``SSE_KEEPALIVE_INTERVAL`` seconds.

    Defined once in a leaf module so every backend yields the same class
    and ``isinstance`` checks in the session-manager SSE pipeline work
    uniformly. Otherwise a Docker-emitted keepalive would be a different
    class than a K8s-emitted keepalive and one would fall through the
    manager's isinstance chain as "unrecognized" and be silently dropped.
    """
