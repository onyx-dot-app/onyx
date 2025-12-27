import ipaddress
import socket
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse

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


def validate_url_for_ssrf(url: str) -> None:
    """
    Validate a URL to prevent Server-Side Request Forgery (SSRF) attacks.

    This function checks that:
    1. The URL uses http or https scheme
    2. The hostname is not a blocked hostname
    3. The hostname does not resolve to a private/internal IP address

    Args:
        url: The URL to validate

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

    # Try to resolve the hostname and check all resolved IPs
    try:
        # First, check if the hostname is already an IP address
        try:
            ip = ipaddress.ip_address(hostname)
            if _is_ip_private_or_reserved(str(ip)):
                raise SSRFException(
                    f"Access to internal/private IP address '{hostname}' is not allowed."
                )
            return
        except ValueError:
            # Not an IP address, proceed with DNS resolution
            pass

        # Resolve hostname to IP addresses
        addr_info = socket.getaddrinfo(
            hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )

        if not addr_info:
            raise SSRFException(f"Could not resolve hostname '{hostname}'")

        # Check all resolved IP addresses
        for info in addr_info:
            ip_str = info[4][0]  # IP address is in the 5th element, first item
            if _is_ip_private_or_reserved(str(ip_str)):
                raise SSRFException(
                    f"Hostname '{hostname}' resolves to internal/private IP address '{ip_str}'. "
                    "Access to internal networks is not allowed."
                )

    except socket.gaierror as e:
        # DNS resolution failed - this could be a valid error or an attempt to use
        # a non-existent domain. We'll allow it and let the actual request fail.
        logger.warning(f"DNS resolution failed for hostname '{hostname}': {e}")
        # Re-raise as SSRFException to be safe - if DNS fails, we shouldn't proceed
        raise SSRFException(f"Could not resolve hostname '{hostname}': {e}")
    except SSRFException:
        raise
    except Exception as e:
        logger.warning(f"Error during SSRF validation for URL '{url}': {e}")
        raise SSRFException(f"URL validation failed: {e}")


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
