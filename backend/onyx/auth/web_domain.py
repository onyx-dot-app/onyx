from urllib.parse import urlsplit

from starlette.requests import HTTPConnection

from onyx.configs.app_configs import ALTERNATE_WEB_DOMAINS, WEB_DOMAIN

# The web server sets this when it forwards a browser request to the API server,
# so the API server sees the browser's host instead of its own internal one.
FORWARDED_HOST_HEADER = "x-forwarded-host"
_HOST_HEADER = "host"


def _alternate_origins_by_host(origins: list[str]) -> dict[str, str]:
    """Map each alternate origin's `host[:port]` to the origin. Fails at startup
    on an entry that is not a bare http(s) origin."""
    origins_by_host: dict[str, str] = {}
    for origin in origins:
        parts = urlsplit(origin)
        if (
            parts.scheme not in ("http", "https")
            or not parts.netloc
            or parts.path
            or parts.query
            or parts.fragment
        ):
            raise ValueError(
                f"ALTERNATE_WEB_DOMAINS entry {origin!r} must be an origin "
                "such as https://onyx.example.com"
            )
        origins_by_host[parts.netloc.lower()] = origin
    return origins_by_host


_ALTERNATE_ORIGINS_BY_HOST = _alternate_origins_by_host(ALTERNATE_WEB_DOMAINS)


def get_request_web_domain(connection: HTTPConnection) -> str:
    """The web origin the browser is on, for URLs that must bring it back to the
    same host (login callbacks and redirects).

    Returns an ALTERNATE_WEB_DOMAINS entry when the request's forwarded host or
    Host header names one, else WEB_DOMAIN. Never builds a URL from a raw
    header, so a spoofed host can only select another configured origin.
    """
    if not _ALTERNATE_ORIGINS_BY_HOST:
        return WEB_DOMAIN

    for header in (FORWARDED_HOST_HEADER, _HOST_HEADER):
        value = connection.headers.get(header)
        if not value:
            continue
        # A proxy chain appends hosts; the first one is the browser's.
        host = value.split(",")[0].strip().lower()
        origin = _ALTERNATE_ORIGINS_BY_HOST.get(host)
        if origin is not None:
            return origin

    return WEB_DOMAIN


def get_allowed_web_origins() -> list[str]:
    """Every origin a browser may use for this deployment."""
    return [WEB_DOMAIN, *ALTERNATE_WEB_DOMAINS]
