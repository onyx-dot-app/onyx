"""
Unit tests for SSRF protection in URL validation utilities.

These tests verify that the validate_url_for_ssrf function correctly blocks
requests to internal/private IP addresses and other potentially dangerous destinations.
"""

import os
from unittest.mock import patch

import pytest

from onyx.utils.url import _is_ip_private_or_reserved
from onyx.utils.url import SSRFException
from onyx.utils.url import validate_url_for_ssrf


class TestIsIpPrivateOrReserved:
    """Tests for the _is_ip_private_or_reserved helper function."""

    def test_loopback_ipv4(self) -> None:
        """Test that IPv4 loopback addresses are detected as private."""
        assert _is_ip_private_or_reserved("127.0.0.1") is True
        assert _is_ip_private_or_reserved("127.0.0.2") is True
        assert _is_ip_private_or_reserved("127.255.255.255") is True

    def test_loopback_ipv6(self) -> None:
        """Test that IPv6 loopback addresses are detected as private."""
        assert _is_ip_private_or_reserved("::1") is True

    def test_private_class_a(self) -> None:
        """Test that private Class A addresses (10.x.x.x) are detected."""
        assert _is_ip_private_or_reserved("10.0.0.1") is True
        assert _is_ip_private_or_reserved("10.255.255.255") is True

    def test_private_class_b(self) -> None:
        """Test that private Class B addresses (172.16-31.x.x) are detected."""
        assert _is_ip_private_or_reserved("172.16.0.1") is True
        assert _is_ip_private_or_reserved("172.31.255.255") is True

    def test_private_class_c(self) -> None:
        """Test that private Class C addresses (192.168.x.x) are detected."""
        assert _is_ip_private_or_reserved("192.168.0.1") is True
        assert _is_ip_private_or_reserved("192.168.255.255") is True

    def test_link_local(self) -> None:
        """Test that link-local addresses are detected as private."""
        assert _is_ip_private_or_reserved("169.254.0.1") is True
        assert _is_ip_private_or_reserved("169.254.255.255") is True

    def test_cloud_metadata_ips(self) -> None:
        """Test that cloud metadata service IPs are detected."""
        assert _is_ip_private_or_reserved("169.254.169.254") is True  # AWS/GCP/Azure
        assert _is_ip_private_or_reserved("169.254.170.2") is True  # AWS ECS

    def test_multicast(self) -> None:
        """Test that multicast addresses are detected."""
        assert _is_ip_private_or_reserved("224.0.0.1") is True
        assert _is_ip_private_or_reserved("239.255.255.255") is True

    def test_unspecified(self) -> None:
        """Test that unspecified addresses are detected."""
        assert _is_ip_private_or_reserved("0.0.0.0") is True
        assert _is_ip_private_or_reserved("::") is True

    def test_public_ips(self) -> None:
        """Test that public IP addresses are not flagged as private."""
        assert _is_ip_private_or_reserved("8.8.8.8") is False  # Google DNS
        assert _is_ip_private_or_reserved("1.1.1.1") is False  # Cloudflare DNS
        assert _is_ip_private_or_reserved("104.16.0.1") is False  # Cloudflare
        assert _is_ip_private_or_reserved("142.250.80.46") is False  # Google

    def test_invalid_ip(self) -> None:
        """Test that invalid IPs are treated as potentially unsafe."""
        assert _is_ip_private_or_reserved("not-an-ip") is True
        assert _is_ip_private_or_reserved("") is True


class TestValidateUrlForSsrf:
    """Tests for the validate_url_for_ssrf function."""

    def test_empty_url(self) -> None:
        """Test that empty URLs raise ValueError."""
        with pytest.raises(ValueError, match="URL cannot be empty"):
            validate_url_for_ssrf("")

    def test_invalid_scheme_ftp(self) -> None:
        """Test that non-HTTP schemes are rejected."""
        with pytest.raises(SSRFException, match="Invalid URL scheme"):
            validate_url_for_ssrf("ftp://example.com/file.txt")

    def test_invalid_scheme_file(self) -> None:
        """Test that file:// scheme is rejected."""
        with pytest.raises(SSRFException, match="Invalid URL scheme"):
            validate_url_for_ssrf("file:///etc/passwd")

    def test_invalid_scheme_gopher(self) -> None:
        """Test that gopher:// scheme is rejected."""
        with pytest.raises(SSRFException, match="Invalid URL scheme"):
            validate_url_for_ssrf("gopher://localhost:70/")

    def test_valid_http_scheme(self) -> None:
        """Test that http scheme is accepted for public URLs."""
        # This should not raise for a public URL
        # Note: This may fail if example.com doesn't resolve in the test env
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 80))  # example.com's IP
            ]
            validate_url_for_ssrf("http://example.com/")

    def test_valid_https_scheme(self) -> None:
        """Test that https scheme is accepted for public URLs."""
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
            validate_url_for_ssrf("https://example.com/")

    def test_localhost_ipv4(self) -> None:
        """Test that localhost (127.0.0.1) is blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            validate_url_for_ssrf("http://127.0.0.1/")

    def test_localhost_hostname(self) -> None:
        """Test that 'localhost' hostname is blocked."""
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]
            with pytest.raises(SSRFException, match="internal/private IP"):
                validate_url_for_ssrf("http://localhost/")

    def test_private_ip_10_network(self) -> None:
        """Test that 10.x.x.x addresses are blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            validate_url_for_ssrf("http://10.0.0.1/")

    def test_private_ip_172_network(self) -> None:
        """Test that 172.16-31.x.x addresses are blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            validate_url_for_ssrf("http://172.16.0.1/")

    def test_private_ip_192_168_network(self) -> None:
        """Test that 192.168.x.x addresses are blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            validate_url_for_ssrf("http://192.168.1.1/")

    def test_aws_metadata_endpoint(self) -> None:
        """Test that AWS metadata endpoint is blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            validate_url_for_ssrf("http://169.254.169.254/latest/meta-data/")

    def test_blocked_hostname_kubernetes(self) -> None:
        """Test that Kubernetes internal hostnames are blocked."""
        with pytest.raises(SSRFException, match="not allowed"):
            validate_url_for_ssrf("http://kubernetes.default.svc.cluster.local/")

    def test_blocked_hostname_metadata_google(self) -> None:
        """Test that Google metadata hostname is blocked."""
        with pytest.raises(SSRFException, match="not allowed"):
            validate_url_for_ssrf("http://metadata.google.internal/")

    def test_url_with_credentials(self) -> None:
        """Test that URLs with embedded credentials are blocked."""
        with pytest.raises(SSRFException, match="embedded credentials"):
            validate_url_for_ssrf("http://user:pass@example.com/")

    def test_url_with_port(self) -> None:
        """Test that URLs with ports are handled correctly."""
        # Internal IP with custom port should be blocked
        with pytest.raises(SSRFException, match="internal/private IP"):
            validate_url_for_ssrf("http://127.0.0.1:8080/metrics")

        # Public IP with custom port should be allowed
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 8080))]
            validate_url_for_ssrf("http://example.com:8080/")

    def test_hostname_resolving_to_private_ip(self) -> None:
        """Test that hostnames resolving to private IPs are blocked."""
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            # Simulate a domain that resolves to a private IP
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.100", 80))]
            with pytest.raises(SSRFException, match="internal/private IP"):
                validate_url_for_ssrf("http://internal-service.company.com/")

    def test_multiple_dns_records_one_private(self) -> None:
        """Test that a hostname with mixed public/private IPs is blocked."""
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            # Simulate a domain with both public and private IPs
            mock_getaddrinfo.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 80)),  # Public
                (2, 1, 6, "", ("10.0.0.1", 80)),  # Private
            ]
            with pytest.raises(SSRFException, match="internal/private IP"):
                validate_url_for_ssrf("http://dual-stack.example.com/")

    def test_dns_resolution_failure(self) -> None:
        """Test that DNS resolution failures are handled safely."""
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            import socket

            mock_getaddrinfo.side_effect = socket.gaierror("Name resolution failed")
            with pytest.raises(SSRFException, match="Could not resolve hostname"):
                validate_url_for_ssrf("http://nonexistent-domain-12345.invalid/")


class TestSsrfProtectionDisabled:
    """Tests for when SSRF protection is disabled via environment variable."""

    def test_disabled_allows_localhost(self) -> None:
        """Test that localhost is allowed when protection is disabled."""
        with patch.dict(os.environ, {"DISABLE_SSRF_PROTECTION": "true"}):
            # Need to reload the module to pick up the env change
            # For this test, we'll just verify the behavior by checking
            # the function doesn't raise
            from importlib import reload

            import onyx.utils.url as url_module

            reload(url_module)

            # This should not raise when protection is disabled
            url_module.validate_url_for_ssrf("http://127.0.0.1/")

            # Restore the module
            with patch.dict(os.environ, {"DISABLE_SSRF_PROTECTION": ""}):
                reload(url_module)
