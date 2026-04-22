"""Extract the real client IP from a FastAPI request.

nginx-ingress forwards the real client address in ``X-Forwarded-For`` while
``request.client.host`` is the in-cluster proxy address. Callers use this for
rate limiting, PostHog ``$ip`` enrichment (drives GeoIP), and abuse attribution.

Only globally-routable addresses are returned so private/loopback/link-local
values (pod-to-pod hops, localhost) never leak into downstream systems as
though they were the client.
"""

import ipaddress

from fastapi import Request


def _is_globally_routable(ip_str: str) -> bool:
    try:
        return ipaddress.ip_address(ip_str).is_global
    except ValueError:
        return False


def get_client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first_hop = xff.split(",")[0].strip()
        if first_hop and _is_globally_routable(first_hop):
            return first_hop
    if request.client and _is_globally_routable(request.client.host):
        return request.client.host
    return None
