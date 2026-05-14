"""
Unit tests for SSRF protection in URL validation utilities.

These tests verify that the SSRF protection correctly blocks
requests to internal/private IP addresses and other potentially dangerous destinations.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.utils.url import _is_ip_private_or_reserved
from onyx.utils.url import _validate_and_resolve_url
from onyx.utils.url import ssrf_safe_get
from onyx.utils.url import SSRFException
from onyx.utils.url import validate_outbound_http_url


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


class TestValidateAndResolveUrl:
    """Tests for the _validate_and_resolve_url function."""

    def test_empty_url(self) -> None:
        """Test that empty URLs raise ValueError."""
        with pytest.raises(ValueError, match="URL cannot be empty"):
            _validate_and_resolve_url("")

    def test_invalid_scheme_ftp(self) -> None:
        """Test that non-HTTP schemes are rejected."""
        with pytest.raises(SSRFException, match="Invalid URL scheme"):
            _validate_and_resolve_url("ftp://example.com/file.txt")

    def test_invalid_scheme_file(self) -> None:
        """Test that file:// scheme is rejected."""
        with pytest.raises(SSRFException, match="Invalid URL scheme"):
            _validate_and_resolve_url("file:///etc/passwd")

    def test_invalid_scheme_gopher(self) -> None:
        """Test that gopher:// scheme is rejected."""
        with pytest.raises(SSRFException, match="Invalid URL scheme"):
            _validate_and_resolve_url("gopher://localhost:70/")

    def test_valid_http_scheme(self) -> None:
        """Test that http scheme is accepted for public URLs."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 80))  # example.com's IP
            ]
            ip, hostname, port = _validate_and_resolve_url("http://example.com/")
            assert ip == "93.184.216.34"
            assert hostname == "example.com"
            assert port == 80

    def test_valid_https_scheme(self) -> None:
        """Test that https scheme is accepted for public URLs."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
            ip, hostname, port = _validate_and_resolve_url("https://example.com/")
            assert ip == "93.184.216.34"
            assert hostname == "example.com"
            assert port == 443

    def test_localhost_ipv4(self) -> None:
        """Test that localhost (127.0.0.1) is blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            _validate_and_resolve_url("http://127.0.0.1/")

    def test_localhost_hostname(self) -> None:
        """Test that 'localhost' hostname is blocked."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]
            with pytest.raises(
                SSRFException, match="Access to hostname 'localhost' is not allowed."
            ):
                _validate_and_resolve_url("http://localhost/")

    def test_private_ip_10_network(self) -> None:
        """Test that 10.x.x.x addresses are blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            _validate_and_resolve_url("http://10.0.0.1/")

    def test_private_ip_172_network(self) -> None:
        """Test that 172.16-31.x.x addresses are blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            _validate_and_resolve_url("http://172.16.0.1/")

    def test_private_ip_192_168_network(self) -> None:
        """Test that 192.168.x.x addresses are blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            _validate_and_resolve_url("http://192.168.1.1/")

    def test_aws_metadata_endpoint(self) -> None:
        """Test that AWS metadata endpoint is blocked."""
        with pytest.raises(
            SSRFException, match="Access to hostname '169.254.169.254' is not allowed."
        ):
            _validate_and_resolve_url("http://169.254.169.254/latest/meta-data/")

    def test_blocked_hostname_kubernetes(self) -> None:
        """Test that Kubernetes internal hostnames are blocked."""
        with pytest.raises(SSRFException, match="not allowed"):
            _validate_and_resolve_url("http://kubernetes.default.svc.cluster.local/")

    def test_blocked_hostname_metadata_google(self) -> None:
        """Test that Google metadata hostname is blocked."""
        with pytest.raises(SSRFException, match="not allowed"):
            _validate_and_resolve_url("http://metadata.google.internal/")

    def test_url_with_credentials(self) -> None:
        """Test that URLs with embedded credentials are blocked."""
        with pytest.raises(SSRFException, match="embedded credentials"):
            _validate_and_resolve_url("http://user:pass@example.com/")

    def test_url_with_port(self) -> None:
        """Test that URLs with ports are handled correctly."""
        # Internal IP with custom port should be blocked
        with pytest.raises(SSRFException, match="internal/private IP"):
            _validate_and_resolve_url("http://127.0.0.1:8080/metrics")

        # Public IP with custom port should be allowed
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 8080))]
            ip, hostname, port = _validate_and_resolve_url("http://example.com:8080/")
            assert ip == "93.184.216.34"
            assert port == 8080

    def test_hostname_resolving_to_private_ip(self) -> None:
        """Test that hostnames resolving to private IPs are blocked."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.100", 80))]
            with pytest.raises(SSRFException, match="internal/private IP"):
                _validate_and_resolve_url("http://internal-service.company.com/")

    def test_multiple_dns_records_one_private(self) -> None:
        """Test that a hostname with mixed public/private IPs is blocked."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 80)),  # Public
                (2, 1, 6, "", ("10.0.0.1", 80)),  # Private
            ]
            with pytest.raises(SSRFException, match="internal/private IP"):
                _validate_and_resolve_url("http://dual-stack.example.com/")

    def test_dns_resolution_failure(self) -> None:
        """Test that DNS resolution failures are handled safely."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            import socket

            mock_getaddrinfo.side_effect = socket.gaierror("Name resolution failed")
            with pytest.raises(SSRFException, match="Could not resolve hostname"):
                _validate_and_resolve_url("http://nonexistent-domain-12345.invalid/")


class TestSsrfSafeGet:
    """Tests for the ssrf_safe_get function."""

    def test_blocks_private_ip(self) -> None:
        """Test that requests to private IPs are blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            ssrf_safe_get("http://192.168.1.1/")

    def test_blocks_localhost(self) -> None:
        """Test that requests to localhost are blocked."""
        with pytest.raises(SSRFException, match="internal/private IP"):
            ssrf_safe_get("http://127.0.0.1/")

    def test_blocks_metadata_endpoint(self) -> None:
        """Test that requests to cloud metadata endpoints are blocked."""
        with pytest.raises(
            SSRFException, match="Access to hostname '169.254.169.254' is not allowed."
        ):
            ssrf_safe_get("http://169.254.169.254/")

    def test_makes_request_to_validated_ip_http(self) -> None:
        """Test that HTTP requests are made to the validated IP."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False

        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]

            with patch("onyx.utils.url.requests.get") as mock_get:
                mock_get.return_value = mock_response

                response = ssrf_safe_get("http://example.com/path")

                # Verify the request was made to the IP, not the hostname
                mock_get.assert_called_once()
                call_args = mock_get.call_args
                assert "93.184.216.34" in call_args[0][0]
                # Verify Host header is set
                assert call_args[1]["headers"]["Host"] == "example.com"
                assert response == mock_response

    def test_makes_request_with_original_url_https(self) -> None:
        """Test that HTTPS requests use original URL for TLS."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False

        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]

            with patch("onyx.utils.url.requests.get") as mock_get:
                mock_get.return_value = mock_response

                response = ssrf_safe_get("https://example.com/path")

                # For HTTPS, we use original URL for TLS
                mock_get.assert_called_once()
                call_args = mock_get.call_args
                assert call_args[0][0] == "https://example.com/path"
                assert response == mock_response

    def test_passes_custom_headers(self) -> None:
        """Test that custom headers are passed through."""
        mock_response = MagicMock()
        mock_response.is_redirect = False

        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]

            with patch("onyx.utils.url.requests.get") as mock_get:
                mock_get.return_value = mock_response

                custom_headers = {"User-Agent": "TestBot/1.0"}
                ssrf_safe_get("http://example.com/", headers=custom_headers)

                call_args = mock_get.call_args
                assert call_args[1]["headers"]["User-Agent"] == "TestBot/1.0"

    def test_passes_timeout(self) -> None:
        """Test that timeout is passed through, including tuple form."""
        mock_response = MagicMock()
        mock_response.is_redirect = False

        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]

            with patch("onyx.utils.url.requests.get") as mock_get:
                mock_get.return_value = mock_response

                ssrf_safe_get("http://example.com/", timeout=(5, 15))

                call_args = mock_get.call_args
                assert call_args[1]["timeout"] == (5, 15)


class TestSsrfSafeGetAllowPrivateNetwork:
    """Tests for the allow_private_network opt-out on ssrf_safe_get."""

    def test_allows_private_ip_when_enabled(self) -> None:
        mock_response = MagicMock()
        mock_response.is_redirect = False

        with patch("onyx.utils.url.requests.get") as mock_get:
            mock_get.return_value = mock_response

            response = ssrf_safe_get("http://192.168.1.1/", allow_private_network=True)

            # Request goes out to the original URL, not pinned to an IP
            mock_get.assert_called_once()
            assert mock_get.call_args[0][0] == "http://192.168.1.1/"
            assert response == mock_response

    def test_allows_hostname_resolving_to_private_ip_when_enabled(self) -> None:
        """Split-horizon DNS (e.g. js.jpl.nasa.gov inside JPL's VPC) should
        succeed when the operator has opted out of the private-IP guard.

        DNS is still resolved on the opt-out path — _hostname_resolves_to_
        always_blocked_ip checks for the loopback/unspecified/link-local
        floor — but RFC1918 results pass through cleanly.
        """
        mock_response = MagicMock()
        mock_response.is_redirect = False

        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("10.0.0.1", 443))]

            with patch("onyx.utils.url.requests.get") as mock_get:
                mock_get.return_value = mock_response

                ssrf_safe_get(
                    "https://js.jpl.nasa.gov/docs",
                    allow_private_network=True,
                )

                mock_get.assert_called_once()
                assert mock_get.call_args[0][0] == "https://js.jpl.nasa.gov/docs"

    def test_still_blocks_metadata_hostname_when_enabled(self) -> None:
        """The blocked-hostname list (e.g. metadata.google.internal) must
        keep working even when the private-IP guard is off — opting into
        private networks shouldn't open up cloud metadata access."""
        with pytest.raises(SSRFException, match="not allowed"):
            ssrf_safe_get(
                "http://metadata.google.internal/latest",
                allow_private_network=True,
            )

    def test_still_blocks_credentials_when_enabled(self) -> None:
        with pytest.raises(SSRFException, match="embedded credentials"):
            ssrf_safe_get("http://user:pass@10.0.0.1/", allow_private_network=True)

    def test_still_blocks_invalid_scheme_when_enabled(self) -> None:
        with pytest.raises(SSRFException, match="Invalid URL scheme"):
            ssrf_safe_get("file:///etc/passwd", allow_private_network=True)

    def test_still_blocks_loopback_ip_when_enabled(self) -> None:
        """Even with the private-network opt-out, the LLM tool must not be
        able to reach the application host's own loopback (admin APIs,
        sidecars)."""
        with pytest.raises(SSRFException, match="loopback/unspecified"):
            ssrf_safe_get("http://127.0.0.1:8080/", allow_private_network=True)

    def test_follows_redirect_to_private_ip_when_enabled(self) -> None:
        """A 302 to another private-network URL should be followed when
        opted in — validation re-runs on each hop and accepts private IPs."""
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"Location": "http://10.0.0.2/final"}

        final_response = MagicMock()
        final_response.is_redirect = False

        with patch("onyx.utils.url.requests.get") as mock_get:
            mock_get.side_effect = [redirect_response, final_response]

            response = ssrf_safe_get(
                "http://10.0.0.1/start", allow_private_network=True
            )

            assert response == final_response
            assert mock_get.call_count == 2
            assert mock_get.call_args_list[1][0][0] == "http://10.0.0.2/final"

    def test_redirect_to_blocked_hostname_is_rejected_when_enabled(self) -> None:
        """A redirect to a blocked hostname (e.g. cloud metadata) must still
        raise, even if the initial hop succeeded under the opt-out."""
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {
            "Location": "http://metadata.google.internal/latest"
        }

        with patch("onyx.utils.url.requests.get") as mock_get:
            mock_get.return_value = redirect_response

            with pytest.raises(SSRFException, match="not allowed"):
                ssrf_safe_get("http://10.0.0.1/start", allow_private_network=True)

    def test_redirect_to_loopback_is_rejected_when_enabled(self) -> None:
        """A redirect to a loopback IP literal must also be rejected — same
        reasoning as the direct-hit case."""
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"Location": "http://127.0.0.1:8080/admin"}

        with patch("onyx.utils.url.requests.get") as mock_get:
            mock_get.return_value = redirect_response

            with pytest.raises(SSRFException, match="loopback/unspecified"):
                ssrf_safe_get("http://10.0.0.1/start", allow_private_network=True)


class TestValidateOutboundHttpUrl:
    def test_rejects_private_ip_by_default(self) -> None:
        with pytest.raises(SSRFException, match="internal/private IP"):
            validate_outbound_http_url("http://10.0.0.1:8000")

    def test_allows_rfc1918_ip_when_explicitly_enabled(self) -> None:
        validated_url = validate_outbound_http_url(
            "http://10.0.0.1:8000", allow_private_network=True
        )
        assert validated_url == "http://10.0.0.1:8000"

    def test_blocks_metadata_hostname_when_private_is_enabled(self) -> None:
        with pytest.raises(SSRFException, match="not allowed"):
            validate_outbound_http_url(
                "http://metadata.google.internal/latest",
                allow_private_network=True,
            )

    def test_allows_loopback_when_private_enabled_without_floor(self) -> None:
        """Admin-configured callers (voice API for local Azure speech
        containers, etc.) explicitly want to reach 127.0.0.1. The
        block_loopback_and_link_local flag stays False by default so
        validate_outbound_http_url(allow_private_network=True) preserves
        that behavior — the stricter floor is opt-in for LLM-controlled
        paths like open_url."""
        validated = validate_outbound_http_url(
            "http://127.0.0.1:5000", allow_private_network=True
        )
        assert validated == "http://127.0.0.1:5000"

    def test_blocks_loopback_ipv4_with_floor(self) -> None:
        """When block_loopback_and_link_local=True (open_url path), loopback
        is rejected even though private networks are otherwise allowed."""
        with pytest.raises(SSRFException, match="loopback/unspecified"):
            validate_outbound_http_url(
                "http://127.0.0.1:8080/",
                allow_private_network=True,
                block_loopback_and_link_local=True,
            )

    def test_blocks_loopback_range_with_floor(self) -> None:
        """Any address in 127.0.0.0/8 must be blocked, not just 127.0.0.1."""
        with pytest.raises(SSRFException, match="loopback/unspecified"):
            validate_outbound_http_url(
                "http://127.1.2.3/",
                allow_private_network=True,
                block_loopback_and_link_local=True,
            )

    def test_blocks_loopback_ipv6_with_floor(self) -> None:
        with pytest.raises(SSRFException, match="loopback/unspecified"):
            validate_outbound_http_url(
                "http://[::1]:8080/",
                allow_private_network=True,
                block_loopback_and_link_local=True,
            )

    def test_blocks_unspecified_ipv4_with_floor(self) -> None:
        with pytest.raises(SSRFException, match="loopback/unspecified"):
            validate_outbound_http_url(
                "http://0.0.0.0/",
                allow_private_network=True,
                block_loopback_and_link_local=True,
            )

    def test_blocks_link_local_ipv4_literal_with_floor(self) -> None:
        """Link-local IPv4 (169.254.0.0/16) is in the always-blocked tier —
        covers the cloud-metadata range. 169.254.169.254 itself is also in
        BLOCKED_HOSTNAMES, but other link-local literals (e.g. 169.254.0.1)
        are not, so the IP-class check is what stops them."""
        with pytest.raises(SSRFException, match="loopback/unspecified/link-local"):
            validate_outbound_http_url(
                "http://169.254.0.1/",
                allow_private_network=True,
                block_loopback_and_link_local=True,
            )

    def test_blocks_link_local_ipv6_literal_with_floor(self) -> None:
        """Link-local IPv6 (fe80::/10) is in the always-blocked tier."""
        with pytest.raises(SSRFException, match="loopback/unspecified/link-local"):
            validate_outbound_http_url(
                "http://[fe80::1]/",
                allow_private_network=True,
                block_loopback_and_link_local=True,
            )

    def test_blocks_dns_name_resolving_to_loopback_with_floor(self) -> None:
        """A DNS name that resolves to 127.0.0.1 must be blocked on the
        floor path — e.g. an attacker-controlled `loopback.attacker.com`
        record could otherwise reach the app host's loopback via open_url."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]
            with pytest.raises(SSRFException, match="resolves to loopback"):
                validate_outbound_http_url(
                    "http://loopback.attacker.com/",
                    allow_private_network=True,
                    block_loopback_and_link_local=True,
                )

    def test_blocks_dns_name_resolving_to_ipv6_loopback_with_floor(self) -> None:
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(30, 1, 6, "", ("::1", 80, 0, 0))]
            with pytest.raises(SSRFException, match="resolves to loopback"):
                validate_outbound_http_url(
                    "http://loopback6.attacker.com/",
                    allow_private_network=True,
                    block_loopback_and_link_local=True,
                )

    def test_blocks_dns_name_resolving_to_unspecified_with_floor(self) -> None:
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("0.0.0.0", 80))]
            with pytest.raises(SSRFException, match="resolves to loopback"):
                validate_outbound_http_url(
                    "http://unspecified.attacker.com/",
                    allow_private_network=True,
                    block_loopback_and_link_local=True,
                )

    def test_blocks_dns_name_resolving_to_aws_metadata_with_floor(self) -> None:
        """The canonical SSRF attack: an attacker-controlled DNS record
        pointing at 169.254.169.254 must not let the LLM tool exfiltrate
        IAM credentials from a cloud-hosted Onyx deployment, even when the
        operator has opted into private networks for their internal docs."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("169.254.169.254", 80))]
            with pytest.raises(SSRFException, match="link-local"):
                validate_outbound_http_url(
                    "http://imds.attacker.com/latest/meta-data/iam/",
                    allow_private_network=True,
                    block_loopback_and_link_local=True,
                )

    def test_blocks_dns_name_resolving_to_link_local_with_floor(self) -> None:
        """Any link-local IPv4 (169.254.0.0/16), not just the metadata IP."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("169.254.42.42", 80))]
            with pytest.raises(SSRFException, match="link-local"):
                validate_outbound_http_url(
                    "http://link-local.attacker.com/",
                    allow_private_network=True,
                    block_loopback_and_link_local=True,
                )

    def test_allows_dns_name_resolving_to_rfc1918_with_floor(self) -> None:
        """The whole point of the opt-out: a DNS name resolving to RFC1918
        should succeed even with the floor on."""
        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [(2, 1, 6, "", ("10.0.0.5", 443))]
            validated = validate_outbound_http_url(
                "https://js.jpl.nasa.gov/",
                allow_private_network=True,
                block_loopback_and_link_local=True,
            )
            assert validated == "https://js.jpl.nasa.gov/"

    def test_dns_failure_does_not_raise_with_floor(self) -> None:
        """If DNS resolution fails during the floor pre-check, don't
        reject — internal-only names that aren't resolvable from the
        validation context should still be allowed (the actual request will
        fail on its own if the name is truly broken). The floor is
        defense-in-depth, not the primary gatekeeper on this path."""
        import socket as socket_module

        with patch("onyx.utils.url.socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = socket_module.gaierror(
                "Name resolution failed"
            )
            validated = validate_outbound_http_url(
                "https://internal-only.company.com/",
                allow_private_network=True,
                block_loopback_and_link_local=True,
            )
            assert validated == "https://internal-only.company.com/"
