"""The guards around downloading a domain list: address, scheme, size, shape."""

import io
from collections.abc import Iterator
from unittest import mock

import pytest
import requests

from onyx.auth.domain_blocklist import (
    MAX_BODY_BYTES,
    RemoteDomainBlocklist,
    normalize_domains,
)

_URL = "https://example.com/domains.txt"
_FETCH = "onyx.auth.domain_blocklist.ssrf_safe_get"


def _blocklist(url: str = _URL) -> RemoteDomainBlocklist:
    return RemoteDomainBlocklist(
        name="test",
        url=url,
        fallback_domains={"builtin.example"},
        parse=lambda body: normalize_domains(body.decode().splitlines()),
    )


def _response(status_code: int, text: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.raw = io.BytesIO(text.encode())
    response.url = _URL
    return response


class TestNormalizeDomains:
    def test_keeps_hostnames_lowercased_and_trimmed(self) -> None:
        assert normalize_domains(
            [" GMail.com ", "sub.Example.co.uk", "xn--80ak6aa92e.com"]
        ) == {"gmail.com", "sub.example.co.uk", "xn--80ak6aa92e.com"}

    @pytest.mark.parametrize(
        "junk",
        (
            "",
            "   ",
            "localhost",
            "<html>",
            "evil.example/../x",
            "user@example.com",
            "-bad.example",
            "bad-.example",
            "has space.example",
            "http://example.com",
        ),
    )
    def test_drops_what_is_not_a_hostname(self, junk: str) -> None:
        assert normalize_domains([junk]) == set()


class TestFetchGuards:
    @pytest.mark.parametrize(
        "url",
        (
            "https://10.0.0.5/domains.txt",  # private network
            "https://127.0.0.1/domains.txt",  # loopback
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "https://localhost/domains.txt",  # blocked hostname
            "https://kubernetes.default.svc/domains.txt",  # cluster API
            "ftp://example.com/domains.txt",  # not http(s)
        ),
    )
    def test_refuses_an_internal_or_odd_address_before_connecting(
        self, url: str
    ) -> None:
        """The SSRF guard rejects these from the URL alone: no request is made
        and the built-in domains stay."""
        blocklist = _blocklist(url)
        with mock.patch("onyx.utils.url._pinned_request") as send:
            blocklist.refresh_now()

        send.assert_not_called()
        assert blocklist.get_domains() == {"builtin.example"}

    def test_fetches_through_the_ssrf_guard_with_the_strict_floor(self) -> None:
        """Every hop is validated by ssrf_safe_get; redirects may not leave
        https when the configured URL is https."""
        blocklist = _blocklist()
        with mock.patch(_FETCH, return_value=_response(200, "listed.example")) as fetch:
            blocklist.refresh_now()

        assert blocklist.get_domains() == {"listed.example", "builtin.example"}
        kwargs = fetch.call_args.kwargs
        assert fetch.call_args.args[0] == _URL
        assert kwargs["allow_private_network"] is False
        assert kwargs["block_loopback_and_link_local"] is True
        assert kwargs["https_only"] is True
        assert kwargs["stream"] is True

    def test_plain_http_url_does_not_demand_https(self) -> None:
        blocklist = _blocklist("http://example.com/domains.txt")
        with mock.patch(_FETCH, return_value=_response(200, "listed.example")) as fetch:
            blocklist.refresh_now()

        assert fetch.call_args.kwargs["https_only"] is False

    def test_refuses_a_body_over_the_cap(self) -> None:
        line = "a-domain-with-a-long-name.example\n"
        text = line * (MAX_BODY_BYTES // len(line) + 2)
        blocklist = _blocklist()
        with mock.patch(_FETCH, return_value=_response(200, text)):
            blocklist.refresh_now()

        assert blocklist.get_domains() == {"builtin.example"}

    def test_stops_reading_at_the_cap(self) -> None:
        """An endless body is abandoned after the cap, not read to the end.
        Without streaming this test would never finish."""
        chunk = b"x" * (64 * 1024)
        served = 0

        def endless() -> Iterator[bytes]:
            nonlocal served
            while True:
                served += 1
                yield chunk

        response = _response(200)
        response.iter_content = mock.MagicMock(  # type: ignore[method-assign]
            return_value=endless()
        )
        response.close = mock.MagicMock()  # type: ignore[method-assign]
        blocklist = _blocklist()
        with mock.patch(_FETCH, return_value=response):
            blocklist.refresh_now()

        assert blocklist.get_domains() == {"builtin.example"}
        # One chunk past the cap, then stop
        assert served == MAX_BODY_BYTES // len(chunk) + 1
        response.close.assert_called_once()

    def test_reads_a_body_under_the_cap_in_chunks(self) -> None:
        response = _response(200)
        response.iter_content = mock.MagicMock(  # type: ignore[method-assign]
            return_value=iter([b"one.exam", b"ple\ntwo.", b"example\n"])
        )
        blocklist = _blocklist()
        with mock.patch(_FETCH, return_value=response):
            blocklist.refresh_now()

        assert blocklist.get_domains() == {
            "one.example",
            "two.example",
            "builtin.example",
        }

    def test_closes_the_response(self) -> None:
        response = _response(200, "listed.example")
        response.close = mock.MagicMock()  # type: ignore[method-assign]
        blocklist = _blocklist()
        with mock.patch(_FETCH, return_value=response):
            blocklist.refresh_now()

        response.close.assert_called_once()
