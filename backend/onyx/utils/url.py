import ipaddress
import socket
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Hostnames that should always be blocked
BLOCKED_HOSTNAMES = {
    # Localhost variations
    "localhost",
    # Cloud metadata endpoints (defense-in-depth, IPs also blocked via _is_ip_private_or_reserved)
    "169.254.169.254",  # AWS/Azure/GCP metadata IP
    "fd00:ec2::254",  # AWS IPv6 metadata
    "metadata.azure.com",
    "metadata.google.internal",
    "metadata.gke.internal",
    # Kubernetes internal
    "kubernetes.default",
    "kubernetes.default.svc",
    "kubernetes.default.svc.cluster.local",
}


class SSRFException(Exception):
    """Exception raised when an SSRF attempt is detected."""


def _is_ip_private_or_reserved(ip_str: str) -> bool:
    """
    Check if an IP address is private, reserved, or otherwise not suitable
    for external requests.

    Uses Python's ipaddress module which handles:
    - Private addresses (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
    - Loopback addresses (127.x.x.x, ::1)
    - Link-local addresses (169.254.x.x including cloud metadata IPs, fe80::/10)
    - Reserved addresses
    - Multicast addresses
    - Unspecified addresses (0.0.0.0, ::)
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        # is_global returns True only for globally routable unicast addresses
        # This excludes private, loopback, link-local, reserved, and unspecified
        # We also need to explicitly check multicast as it's not covered by is_global
        return not ip.is_global or ip.is_multicast
    except ValueError:
        # If we can't parse the IP, consider it unsafe
        return True


def _is_targeted_blocked_ip(
    ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    block_loopback: bool,
    block_link_local: bool,
) -> bool:
    """IP classes to reject even when private networks are allowed. Unspecified
    (0.0.0.0, ::) always — the kernel aliases it to loopback. Loopback and
    link-local (169.254.0.0/16, the cloud-metadata range) per flag, so MCP
    opt-ins can permit loopback while IMDS stays unreachable."""
    if ip_obj.is_unspecified:
        return True
    if block_loopback and ip_obj.is_loopback:
        return True
    if block_link_local and ip_obj.is_link_local:
        return True
    return False


def _hostname_resolves_to_targeted_blocked_ip(
    hostname: str, *, block_loopback: bool, block_link_local: bool
) -> str | None:
    """Resolve ``hostname`` and return the first targeted-blocked address (see
    ``_is_targeted_blocked_ip``), keeping the floor for DNS names like
    ``imds.attacker.com`` → 169.254.169.254. None on DNS failure — the real
    request fails on its own, and a name reachable from the runtime but not the
    validation context shouldn't be spuriously rejected."""
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return None

    for info in addr_info:
        ip_str = str(info[4][0])
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_targeted_blocked_ip(
            ip_obj, block_loopback=block_loopback, block_link_local=block_link_local
        ):
            return ip_str
    return None


def _validate_and_resolve_url(url: str) -> tuple[str, str, int]:
    """
    Validate a URL for SSRF and resolve it to a safe IP address.

    Returns:
        Tuple of (validated_ip, original_hostname, port)

    Raises:
        SSRFException: If the URL could be used for SSRF attack
        ValueError: If the URL is malformed
    """
    if not url:
        raise ValueError("URL cannot be empty")

    # Parse the URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL format: {e}")

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise SSRFException(
            f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed."
        )

    # Get hostname
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must contain a hostname")

    # Check for blocked hostnames
    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_HOSTNAMES:
        raise SSRFException(f"Access to hostname '{hostname}' is not allowed.")

    # Check for common SSRF bypass attempts
    # Block URLs with credentials (user:pass@host)
    if parsed.username or parsed.password:
        raise SSRFException("URLs with embedded credentials are not allowed.")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Check if the hostname is already an IP address
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_ip_private_or_reserved(str(ip)):
            raise SSRFException(
                f"Access to internal/private IP address '{hostname}' is not allowed."
            )
        return str(ip), hostname, port
    except ValueError:
        # Not an IP address, proceed with DNS resolution
        pass

    # Resolve hostname to IP addresses
    try:
        addr_info = socket.getaddrinfo(hostname, port)
    except socket.gaierror as e:
        logger.warning("DNS resolution failed for hostname '%s': %s", hostname, e)
        raise SSRFException(f"Could not resolve hostname '{hostname}': {e}")

    if not addr_info:
        raise SSRFException(f"Could not resolve hostname '{hostname}'")

    # Find the first valid (non-private) IP address
    validated_ip = None
    for info in addr_info:
        ip_str = info[4][0]
        if _is_ip_private_or_reserved(str(ip_str)):
            raise SSRFException(
                f"Hostname '{hostname}' resolves to internal/private IP address "
                f"'{ip_str}'. Access to internal networks is not allowed."
            )
        if validated_ip is None:
            validated_ip = ip_str

    if validated_ip is None:
        raise SSRFException(f"Could not resolve hostname '{hostname}'")

    return validated_ip, hostname, port  # ty: ignore[invalid-return-type]


def _enforce_targeted_block(
    display_host: str,
    hostname: str,
    *,
    block_loopback: bool,
    block_link_local: bool,
    resolve_dns: bool,
) -> None:
    """Reject ``hostname`` if it (or its DNS resolution) lands in a targeted-
    blocked class, used on the ``allow_private_network=True`` path. Literal IPs
    are classified directly; DNS names are resolved only when ``resolve_dns``."""
    try:
        ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address | None = (
            ipaddress.ip_address(hostname)
        )
    except ValueError:
        ip_obj = None

    if ip_obj is not None:
        if _is_targeted_blocked_ip(
            ip_obj, block_loopback=block_loopback, block_link_local=block_link_local
        ):
            raise SSRFException(
                f"Access to loopback/unspecified/link-local IP "
                f"'{display_host}' is not allowed."
            )
        return

    if not resolve_dns:
        return

    blocked_ip = _hostname_resolves_to_targeted_blocked_ip(
        hostname, block_loopback=block_loopback, block_link_local=block_link_local
    )
    if blocked_ip is not None:
        raise SSRFException(
            f"Hostname '{display_host}' resolves to loopback/"
            f"unspecified/link-local IP '{blocked_ip}'. Access is not allowed."
        )


def validate_outbound_http_url(
    url: str,
    *,
    allow_private_network: bool = False,
    https_only: bool = False,
    block_loopback_and_link_local: bool = False,
    block_link_local_only: bool = False,
    resolve_dns: bool = True,
) -> str:
    """Validate a URL for backend outbound HTTP calls; returns the whitespace-
    stripped URL or raises ``SSRFException``/``ValueError``.

    ``allow_private_network`` skips the private/reserved-IP guard for trusted
    networks. When it's on, ``block_loopback_and_link_local`` keeps the strict
    floor (loopback + unspecified + link-local) for LLM-controlled paths like
    ``open_url``, while ``block_link_local_only`` permits loopback but still
    blocks cloud-metadata — for MCP opt-ins where a local/sidecar server is
    legitimate. ``https_only`` rejects http://. ``resolve_dns=False`` skips the
    DNS lookup (structural + literal-IP checks only), for config-save time where
    a placeholder/transient host shouldn't block a save; fetch time still
    resolves."""
    normalized_url = url.strip()
    if not normalized_url:
        raise ValueError("URL cannot be empty")

    parsed = urlparse(normalized_url)

    if https_only:
        if parsed.scheme != "https":
            raise SSRFException(
                f"Invalid URL scheme '{parsed.scheme}'. Only https is allowed."
            )
    elif parsed.scheme not in ("http", "https"):
        raise SSRFException(
            f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed."
        )

    if not parsed.hostname:
        raise ValueError("URL must contain a hostname")

    if parsed.username or parsed.password:
        raise SSRFException("URLs with embedded credentials are not allowed.")

    hostname = parsed.hostname.lower()
    if hostname in BLOCKED_HOSTNAMES:
        raise SSRFException(f"Access to hostname '{parsed.hostname}' is not allowed.")

    block_loopback = block_loopback_and_link_local
    block_link_local = block_loopback_and_link_local or block_link_local_only

    if allow_private_network:
        if block_loopback or block_link_local:
            _enforce_targeted_block(
                parsed.hostname,
                hostname,
                block_loopback=block_loopback,
                block_link_local=block_link_local,
                resolve_dns=resolve_dns,
            )
        return normalized_url

    # allow_private_network is False: reject all private/reserved targets.
    try:
        ip_obj = ipaddress.ip_address(hostname)
    except ValueError:
        ip_obj = None

    if ip_obj is not None:
        if _is_ip_private_or_reserved(str(ip_obj)):
            raise SSRFException(
                f"Access to internal/private IP address '{parsed.hostname}' "
                "is not allowed."
            )
        return normalized_url

    # Hostname (not a literal IP); skip the DNS-resolving guard at save time.
    if resolve_dns:
        _validate_and_resolve_url(normalized_url)

    return normalized_url


MAX_REDIRECTS = 10


class _PinnedHostAdapter(HTTPAdapter):
    """Connects to a pre-validated IP while doing TLS against the real
    hostname (SNI and certificate verification), so the request cannot
    re-resolve DNS after validation (rebinding defense)."""

    def __init__(self, hostname: str, **kwargs: Any) -> None:
        self._hostname = hostname
        super().__init__(**kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        kwargs["server_hostname"] = self._hostname
        kwargs["assert_hostname"] = self._hostname
        super().init_poolmanager(*args, **kwargs)


def _pinned_get(
    url: str,
    validated_ip: str,
    hostname: str,
    port: int,
    headers: dict[str, str] | None,
    timeout: float | tuple[float, float],
    **kwargs: Any,
) -> requests.Response:
    """GET the already-validated IP directly, presenting ``hostname`` for the
    Host header and (on https) SNI + certificate verification."""
    parsed = urlparse(url)
    ip_literal = f"[{validated_ip}]" if ":" in validated_ip else validated_ip
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = f"{ip_literal}:{port}" if port != default_port else ip_literal
    request_url = urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, "")
    )
    request_headers = headers.copy() if headers else {}
    request_headers["Host"] = f"{hostname}:{port}" if port != default_port else hostname

    if parsed.scheme != "https":
        return requests.get(
            request_url,
            headers=request_headers,
            timeout=timeout,
            allow_redirects=False,
            **kwargs,
        )

    with requests.Session() as session:
        session.mount("https://", _PinnedHostAdapter(hostname))
        return session.get(
            request_url,
            headers=request_headers,
            timeout=timeout,
            allow_redirects=False,
            **kwargs,
        )


def _resolve_permissive_ip(
    hostname: str,
    port: int,
    *,
    block_loopback: bool,
    block_link_local: bool,
) -> str:
    """One DNS resolution for the permissive path: any address is acceptable
    except the targeted-blocked classes the caller keeps."""
    try:
        return str(ipaddress.ip_address(hostname))
    except ValueError:
        pass
    try:
        addr_info = socket.getaddrinfo(hostname, port)
    except socket.gaierror as e:
        raise SSRFException(f"Could not resolve hostname '{hostname}': {e}")
    for info in addr_info:
        ip_str = str(info[4][0])
        if not _is_targeted_blocked_ip(
            ipaddress.ip_address(ip_str),
            block_loopback=block_loopback,
            block_link_local=block_link_local,
        ):
            return ip_str
    raise SSRFException(
        f"Hostname '{hostname}' resolves only to blocked address classes."
    )


def _make_ssrf_safe_request(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float | tuple[float, float] = 15,
    allow_private_network: bool = False,
    block_loopback_and_link_local: bool = True,
    block_link_local_only: bool = False,
    https_only: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """
    Make a single GET request with SSRF protection (no redirect following).

    Returns the response which may be a redirect (3xx status).

    The hostname is resolved exactly once, validated, and the request is made
    directly to the validated IP (with Host/SNI set to the hostname), so a
    rebinding DNS server cannot swap the destination after validation.

    When ``allow_private_network`` is True, the private-IP guard is skipped
    so operators on trusted networks can fetch URLs that resolve to RFC1918
    addresses. ``block_loopback_and_link_local`` (default True) keeps the
    strict floor for LLM-controlled callers; admin-configured paths may lower
    it to ``block_link_local_only`` so loopback services are reachable while
    cloud-metadata stays blocked.
    """
    if https_only and urlparse(url).scheme != "https":
        raise SSRFException(
            f"Invalid URL scheme '{urlparse(url).scheme}'. Only https is allowed."
        )

    if allow_private_network:
        validate_outbound_http_url(
            url,
            allow_private_network=True,
            block_loopback_and_link_local=block_loopback_and_link_local,
            block_link_local_only=block_link_local_only,
            https_only=https_only,
        )
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        block_loopback = block_loopback_and_link_local
        block_link_local = block_loopback_and_link_local or block_link_local_only
        validated_ip = _resolve_permissive_ip(
            hostname,
            port,
            block_loopback=block_loopback,
            block_link_local=block_link_local,
        )
        return _pinned_get(
            url, validated_ip, hostname, port, headers, timeout, **kwargs
        )

    # Validate and resolve the URL to get a safe IP
    validated_ip, original_hostname, port = _validate_and_resolve_url(url)
    return _pinned_get(
        url, validated_ip, original_hostname, port, headers, timeout, **kwargs
    )


def ssrf_safe_get(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float | tuple[float, float] = 15,
    follow_redirects: bool = True,
    allow_private_network: bool = False,
    block_loopback_and_link_local: bool = True,
    block_link_local_only: bool = False,
    https_only: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """
    Make a GET request with SSRF protection.

    This function resolves the hostname, validates the IP is not private/internal,
    and makes the request directly to the validated IP to prevent DNS rebinding attacks.
    Redirects are followed safely by validating each redirect URL.

    Args:
        url: The URL to fetch
        headers: Optional headers to include in the request
        timeout: Request timeout in seconds
        follow_redirects: Whether to follow redirects (each redirect URL is validated)
        allow_private_network: If True, allow URLs that resolve to private/internal
            IPs. Use only when the operator has explicitly opted in (e.g. trusted
            self-hosted deployment fetching internal docs). Scheme, credential, and
            blocked-hostname checks still apply on each hop.
        **kwargs: Additional arguments passed to requests.get()

    Returns:
        requests.Response object

    Raises:
        SSRFException: If the URL could be used for SSRF attack
        ValueError: If the URL is malformed
        requests.RequestException: If the request fails
    """
    response = _make_ssrf_safe_request(
        url,
        headers,
        timeout,
        allow_private_network=allow_private_network,
        block_loopback_and_link_local=block_loopback_and_link_local,
        block_link_local_only=block_link_local_only,
        https_only=https_only,
        **kwargs,
    )

    if not follow_redirects:
        return response

    # Manually follow redirects while validating each redirect URL
    redirect_count = 0
    current_url = url

    while response.is_redirect and redirect_count < MAX_REDIRECTS:
        redirect_count += 1

        # Get the redirect location
        redirect_url = response.headers.get("Location")
        if not redirect_url:
            break

        # Handle relative redirects
        if not redirect_url.startswith(("http://", "https://")):
            parsed_current = urlparse(current_url)
            if redirect_url.startswith("/"):
                redirect_url = (
                    f"{parsed_current.scheme}://{parsed_current.netloc}{redirect_url}"
                )
            else:
                # Relative path
                base_path = parsed_current.path.rsplit("/", 1)[0]
                redirect_url = f"{parsed_current.scheme}://{parsed_current.netloc}{base_path}/{redirect_url}"

        # Validate and follow the redirect (this will raise SSRFException if invalid)
        current_url = redirect_url
        response = _make_ssrf_safe_request(
            redirect_url,
            headers,
            timeout,
            allow_private_network=allow_private_network,
            block_loopback_and_link_local=block_loopback_and_link_local,
            block_link_local_only=block_link_local_only,
            https_only=https_only,
            **kwargs,
        )

    if response.is_redirect and redirect_count >= MAX_REDIRECTS:
        raise SSRFException(f"Too many redirects (max {MAX_REDIRECTS})")

    return response


def normalize_url(url: str) -> str:
    """
    Normalize a URL by removing query parameters and fragments.
    This is used to create consistent cache keys for deduplication.

    Args:
        url: The original URL

    Returns:
        Normalized URL (scheme + netloc + path + params only)
    """
    parsed_url = urlparse(url)

    # Reconstruct the URL without query string and fragment
    normalized = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            "",
            "",
        )
    )

    return normalized


def add_url_params(url: str, params: dict) -> str:
    """
    Add parameters to a URL, handling existing parameters properly.

    Args:
        url: The original URL
        params: Dictionary of parameters to add

    Returns:
        URL with added parameters
    """
    # Parse the URL
    parsed_url = urlparse(url)

    # Get existing query parameters
    query_params = parse_qs(parsed_url.query)

    # Update with new parameters
    for key, value in params.items():
        query_params[key] = [value]

    # Build the new query string
    new_query = urlencode(query_params, doseq=True)

    # Reconstruct the URL with the new query string
    new_url = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment,
        )
    )

    return new_url


def sanitize_next_url(next_url: str | None) -> str:
    """Validate a post-login redirect target, returning a safe value.

    Only same-origin relative paths are permitted. Anything carrying a scheme
    (e.g. ``javascript:``), a network location (``https://evil.com``), or a
    protocol-relative form (``//evil.com``, ``/\\evil.com``) falls back to
    ``"/"``. This prevents open-redirect / post-auth phishing through the OAuth
    ``next`` parameter.
    """
    if not next_url:
        return "/"

    # Leading/trailing whitespace is ignored by browsers; strip so the checks
    # below see what the browser will actually navigate to.
    next_url = next_url.strip()
    if not next_url:
        return "/"

    # Some browsers strip a leading control character and then reinterpret the
    # remainder as scheme-relative (e.g. "\x01//evil.com" -> "//evil.com").
    if unicodedata.category(next_url[0])[0] == "C":
        return "/"

    # Browsers treat backslashes as forward slashes, so normalize before the
    # checks below — otherwise tricks like "/\\evil.com" slip past as a path.
    normalized = next_url.replace("\\", "/")

    # Reject protocol-relative ("//evil.com") and Chrome's absolute "///" form.
    if not normalized.startswith("/") or normalized.startswith("//"):
        return "/"

    try:
        parsed = urlparse(normalized)
    except ValueError:
        # Malformed input (e.g. invalid IPv6 literal) — fall back to safe default.
        return "/"

    if parsed.scheme or parsed.netloc:
        return "/"

    return next_url
