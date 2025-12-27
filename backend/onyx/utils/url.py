import ipaddress
import socket
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse

import requests

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Hostnames that should always be blocked
BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.gke.internal",
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
        logger.warning(f"DNS resolution failed for hostname '{hostname}': {e}")
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

    return validated_ip, hostname, port


def ssrf_safe_get(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    **kwargs: Any,
) -> requests.Response:
    """
    Make a GET request with SSRF protection.

    This function resolves the hostname, validates the IP is not private/internal,
    and makes the request directly to the validated IP to prevent DNS rebinding attacks.

    Args:
        url: The URL to fetch
        headers: Optional headers to include in the request
        timeout: Request timeout in seconds
        **kwargs: Additional arguments passed to requests.get()

    Returns:
        requests.Response object

    Raises:
        SSRFException: If the URL could be used for SSRF attack
        ValueError: If the URL is malformed
        requests.RequestException: If the request fails
    """
    # Validate and resolve the URL to get a safe IP
    validated_ip, original_hostname, port = _validate_and_resolve_url(url)

    # Parse the URL to rebuild it with the IP
    parsed = urlparse(url)

    # Build the new URL using the validated IP
    # For HTTPS, we need to use the original hostname for TLS verification
    if parsed.scheme == "https":
        # For HTTPS, make request to original URL but we've validated the IP
        # The TLS handshake needs the hostname for SNI
        # We rely on the short time window between validation and request
        # A more robust solution would require custom SSL context
        request_url = url
    else:
        # For HTTP, we can safely request directly to the IP
        netloc = f"{validated_ip}:{port}" if port not in (80, 443) else validated_ip
        request_url = urlunparse(
            (
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )

    # Prepare headers
    request_headers = headers.copy() if headers else {}

    # Set Host header to original hostname (required for virtual hosting)
    if parsed.scheme == "http":
        request_headers["Host"] = (
            f"{original_hostname}:{port}" if port != 80 else original_hostname
        )

    return requests.get(request_url, headers=request_headers, timeout=timeout, **kwargs)


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
