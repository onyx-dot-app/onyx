"""Free-mail domains: the curated list, the downloaded list, and its parsing."""

import io
from collections.abc import Generator
from unittest import mock

import pytest
import requests

from onyx.auth.domain_blocklist import RemoteDomainBlocklist
from onyx.auth.free_mail_email_validator import (
    CURATED_FREE_MAIL_DOMAINS,
    MIN_DOWNLOADED_DOMAINS,
    free_mail_domain_blocklist,
    is_free_mail_email,
)

_TEST_URL = "https://example.com/free-domains.csv"


def _response(status_code: int, text: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.raw = io.BytesIO(text.encode())
    response.url = _TEST_URL
    return response


def _list_of(*domains: str) -> str:
    """A body with enough filler lines to pass the size check."""
    filler = [f"filler-{i}.example" for i in range(MIN_DOWNLOADED_DOMAINS)]
    return "\n".join([*domains, *filler])


@pytest.fixture(autouse=True)
def no_network() -> Generator[mock.MagicMock, None, None]:
    """Unit tests never reach HubSpot. The default answer is a valid list
    with one downloaded domain."""
    with mock.patch("onyx.auth.domain_blocklist.ssrf_safe_get") as fetch:
        fetch.return_value = _response(200, _list_of("downloaded.example"))
        yield fetch


@pytest.fixture
def blocklist() -> RemoteDomainBlocklist:
    return free_mail_domain_blocklist()


class TestCuratedList:
    def test_is_lower_case_and_trimmed(self) -> None:
        for domain in CURATED_FREE_MAIL_DOMAINS:
            assert domain == domain.strip().lower()
            assert "@" not in domain

    @pytest.mark.parametrize(
        "domain",
        (
            "gmail.com",
            "googlemail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "icloud.com",
            "aol.com",
            "proton.me",
            "pm.me",
            "gmx.de",
            "yandex.ru",
            "mail.com",
            "zoho.com",
            "hey.com",
        ),
    )
    def test_has_the_common_providers(self, domain: str) -> None:
        assert domain in CURATED_FREE_MAIL_DOMAINS

    def test_applies_before_any_download(
        self, blocklist: RemoteDomainBlocklist
    ) -> None:
        """The first sign-up after a restart is answered from the curated list."""
        assert blocklist.contains_email_domain("Someone@GMail.com") is True
        assert blocklist.contains_email_domain("someone@example.com") is False
        # Join the refresh the first check started
        blocklist.refresh_now()


class TestDownloadedList:
    def test_adds_to_the_curated_list(self, blocklist: RemoteDomainBlocklist) -> None:
        blocklist.refresh_now()

        assert blocklist.contains_email_domain("someone@downloaded.example") is True
        assert blocklist.contains_email_domain("someone@gmail.com") is True
        assert blocklist.contains_email_domain("someone@example.com") is False

    def test_parses_one_domain_per_line(
        self, blocklist: RemoteDomainBlocklist, no_network: mock.MagicMock
    ) -> None:
        no_network.return_value = _response(
            200,
            _list_of(" Mixed.Case ", "", "with.example,comma.example", "\t", "<html>"),
        )
        blocklist.refresh_now()
        domains = blocklist.get_domains()

        assert "mixed.case" in domains
        assert "with.example" in domains
        assert "comma.example" in domains
        assert "" not in domains
        assert "<html>" not in domains

    def test_a_short_body_keeps_the_last_list(
        self, blocklist: RemoteDomainBlocklist, no_network: mock.MagicMock
    ) -> None:
        """A truncated or HTML answer must not replace a good list."""
        blocklist.refresh_now()

        no_network.return_value = _response(200, "<html>Not Found</html>")
        blocklist.refresh_now()

        assert blocklist.contains_email_domain("someone@downloaded.example") is True

    def test_follows_the_redirect_to_hubspots_cdn(
        self, blocklist: RemoteDomainBlocklist, no_network: mock.MagicMock
    ) -> None:
        """The documented URL answers 307 to HubSpot's CDN. The SSRF-guarded
        fetch follows it, validating each hop, and keeps https."""
        blocklist.refresh_now()

        assert no_network.call_args.args[0].startswith("https://")
        assert no_network.call_args.kwargs.get("follow_redirects", True) is True
        assert no_network.call_args.kwargs["https_only"] is True

    def test_no_url_means_curated_only(self, no_network: mock.MagicMock) -> None:
        with mock.patch(
            "onyx.auth.free_mail_email_validator.FREE_MAIL_DOMAINS_URL", ""
        ):
            blocklist = free_mail_domain_blocklist()
        blocklist.refresh_now()

        assert blocklist.get_domains() == set(CURATED_FREE_MAIL_DOMAINS)
        no_network.assert_not_called()


class TestModuleCheck:
    @pytest.mark.parametrize(
        "email",
        ("someone@gmail.com", "Someone@PROTON.me", "x@yandex.ru"),
    )
    def test_free_mail(self, email: str) -> None:
        assert is_free_mail_email(email) is True

    @pytest.mark.parametrize(
        "email",
        ("someone@example.com", "someone@onyx.app", "", "nodomain", "@gmail.com"),
    )
    def test_not_free_mail(self, email: str) -> None:
        assert is_free_mail_email(email) is False
