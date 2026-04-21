"""Per-IP rate limit on email/password signup.

Orthogonal to reCAPTCHA. Even when bots pass a v3 score >= threshold (real
browser automation + residential proxies routinely do) the cost of each
rotated IP still limits throughput. Cloud-only: self-hosted deployments
skip this entirely.

Uses Redis INCR + EXPIRE (in a pipeline for atomicity) so counters are
cluster-wide. Keys are hour-bucketed on wall-clock so the "per hour" window
is a fixed tumbling window — fine for this use case since we're not trying
to be precise, we're raising cost.

### IP extraction in Onyx cloud

The multi-tenant cloud topology is:

    client  ──(TCP)──▶  AWS NLB  ──(TCP)──▶  ingress-nginx
                                                    │
                                                    ▼
                                             internal nginx
                                                    │
                                                    ▼
                                                api-server

- The NLB is **Layer 4** and does not touch HTTP — it does NOT add
  X-Forwarded-For. With `externalTrafficPolicy: Local` set on the ingress
  service, NLB preserves the source IP at the TCP level.
- ingress-nginx-controller with default config (no `use-forwarded-headers`)
  **ignores any client-supplied X-Forwarded-For** and overwrites it with
  its own `$remote_addr` — which is the real client IP, preserved through
  NLB. So by the time the request leaves ingress-nginx, X-Forwarded-For
  carries exactly one trustworthy entry: the real client.
- internal nginx then appends its own `$remote_addr` (the ingress-nginx
  pod IP, a private RFC-1918 address) via `$proxy_add_x_forwarded_for`.

At the api-server we therefore see:

    X-Forwarded-For: <real_client_ip>, <ingress_nginx_pod_ip>

Taking `parts[0]` matches what the existing nginx-side `limit_req_zone`
already does (`map $http_x_forwarded_for $real_client_ip` in
`onyx-nginx-conf`). It is safe *because* ingress-nginx overwrites XFF —
not because XFF is inherently trustworthy.

Defense in depth: if ingress-nginx is ever reconfigured with
`use-forwarded-headers: true` (making the leftmost entry spoofable again),
we reject leftmost entries that are private / loopback / reserved and
fall through to `request.client.host`. That prevents an attacker from
trivially bucketing all their requests under `10.0.0.1` via an
`X-Forwarded-For: 10.0.0.1` header.

### Prerequisite: ingress-nginx must NOT run with `--enable-ssl-passthrough`

Pre-2026-04-20, the ingress-nginx deployment ran with
`--enable-ssl-passthrough`, which wraps the main nginx in an internal
TCP proxy on `127.0.0.1:442`. That made `$remote_addr` at ingress-nginx
always `127.0.0.1`, so XFF carried loopback for every request. The arg
was removed in `cloud-deployment-yamls#256`. If it is ever re-added,
`parts[0]` will be `127.0.0.1` and `is_global` will correctly reject it
— every signup will bucket under the TCP peer (ingress pod IP), which
degrades rate limiting to a single cluster-wide counter. Safe-fails
(over-rate-limits rather than under-rate-limits) but bad UX, so this
flag must stay off.
"""

import ipaddress
import time

from fastapi import Request

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

# Hardcoded tunables. Registration is a rare legitimate event — humans sign
# up once. 5/hour/IP still accommodates shared-NAT offices while forcing
# bot farms to rotate IPs (which costs real money on residential proxies).
_PER_IP_PER_HOUR = 5
_BUCKET_SECONDS = 3600
_REDIS_KEY_PREFIX = "signup_rate:"


def _is_usable_client_ip(ip_str: str) -> bool:
    """Only accept a parseable, globally-routable IP as the rate-limit key.

    `is_global` is True iff the address is in public-internet space —
    it rules out RFC-1918 private ranges, loopback, link-local,
    multicast, and the RFC-5737 documentation ranges in one check. Any
    non-global address reaching `parts[0]` in Onyx cloud is either a
    kubernetes-internal hop (misconfigured ingress) or an attacker
    spoofing the header, and we fall back to the TCP peer instead.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_global


def _client_ip(request: Request) -> str:
    """Extract the real client IP for the rate-limit key.

    Onyx cloud: the first X-Forwarded-For entry is the real client,
    written by ingress-nginx from its own `$remote_addr` (safe because
    ingress-nginx overwrites, not appends). Later entries are internal
    kubernetes proxy hops. See module docstring for the full rationale.

    Falls back to `request.client.host` (TCP peer) when XFF is absent,
    malformed, or yields an internal-only address — i.e. local dev,
    tests, or a misconfigured ingress.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts and _is_usable_client_ip(parts[0]):
            return parts[0]
    return request.client.host if request.client else "unknown"


def _bucket_key(ip: str) -> str:
    bucket = int(time.time() // _BUCKET_SECONDS)
    return f"{_REDIS_KEY_PREFIX}{ip}:{bucket}"


def is_signup_rate_limit_enabled() -> bool:
    """Only active on multi-tenant cloud deployments. Self-hosted signup is
    typically admin-invite-only and doesn't see the spray-registration
    threat model."""
    return MULTI_TENANT


async def enforce_signup_rate_limit(request: Request) -> None:
    """Raise OnyxError(RATE_LIMITED) if this client has exceeded the hourly
    signup cap. Fails open on Redis errors so a Redis blip cannot block
    legitimate registrations."""
    if not is_signup_rate_limit_enabled():
        return

    ip = _client_ip(request)
    key = _bucket_key(ip)

    try:
        redis = await get_async_redis_connection()
        # INCR + EXPIRE must be atomic: if INCR created the key but EXPIRE
        # then failed separately, the key would live forever with no TTL,
        # permanently blocking that IP after it crossed the threshold.
        # A single pipeline round-trip guarantees both or neither.
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _BUCKET_SECONDS)
        incr_result, _ = await pipe.execute()
        count = int(incr_result)
    except Exception as e:
        logger.error(f"Signup rate-limit Redis error (failing open): {e}")
        return

    if count > _PER_IP_PER_HOUR:
        logger.warning(
            f"Signup rate limit exceeded for ip={ip} count={count} limit={_PER_IP_PER_HOUR}"
        )
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            "Too many signup attempts from this network. Please wait before trying again.",
        )


# Exported for tests that want to reason about the bucket shape without
# re-deriving the constants.
__all__ = [
    "enforce_signup_rate_limit",
    "is_signup_rate_limit_enabled",
    "_PER_IP_PER_HOUR",
    "_BUCKET_SECONDS",
    "_client_ip",
    "_bucket_key",
]
