"""
Tests for disposable email validation.
"""

from collections.abc import Generator
from unittest import mock

import httpx
import pytest

from onyx.auth.disposable_email_validator import (
    DisposableEmailValidator,
    is_disposable_email,
)

_TEST_URL = "https://example.com/domains.json"
_ETAG = '"6a919fa3-14d4e7"'
_LAST_MODIFIED = "Fri, 28 Aug 2026 14:48:03 GMT"


@pytest.fixture
def fresh_validator() -> Generator[DisposableEmailValidator, None, None]:
    """Provide a non-singleton validator instance and restore the singleton."""
    original = DisposableEmailValidator._instance
    DisposableEmailValidator._instance = None
    try:
        yield DisposableEmailValidator()
    finally:
        DisposableEmailValidator._instance = original


def _response(
    status_code: int,
    json_body: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=json_body,
        headers=headers,
        request=httpx.Request("GET", _TEST_URL),
    )


class TestConditionalFetch:
    """Test ETag / Last-Modified handling when fetching the domain list."""

    def test_first_fetch_sends_no_conditional_headers_and_stores_validators(
        self, fresh_validator: DisposableEmailValidator
    ) -> None:
        with mock.patch(
            "onyx.auth.disposable_email_validator.httpx.Client"
        ) as mock_client:
            client = mock_client.return_value.__enter__.return_value
            client.get.return_value = _response(
                200,
                json_body=["fetched-domain.example"],
                headers={"ETag": _ETAG, "Last-Modified": _LAST_MODIFIED},
            )

            domains = fresh_validator.get_domains()

        sent_headers = client.get.call_args.kwargs["headers"]
        assert "If-None-Match" not in sent_headers
        assert "If-Modified-Since" not in sent_headers

        assert "fetched-domain.example" in domains
        assert fresh_validator._etag == _ETAG
        assert fresh_validator._last_modified == _LAST_MODIFIED

    def test_304_keeps_cached_domains(
        self, fresh_validator: DisposableEmailValidator
    ) -> None:
        with mock.patch(
            "onyx.auth.disposable_email_validator.httpx.Client"
        ) as mock_client:
            client = mock_client.return_value.__enter__.return_value
            client.get.return_value = _response(
                200,
                json_body=["fetched-domain.example"],
                headers={"ETag": _ETAG, "Last-Modified": _LAST_MODIFIED},
            )
            fresh_validator.get_domains()

            # Expire the cache and answer the refresh with a 304
            fresh_validator._last_fetch_time = 0
            client.get.return_value = _response(304)
            domains = fresh_validator.get_domains()

        sent_headers = client.get.call_args.kwargs["headers"]
        assert sent_headers["If-None-Match"] == _ETAG
        assert sent_headers["If-Modified-Since"] == _LAST_MODIFIED

        assert "fetched-domain.example" in domains
        assert fresh_validator._etag == _ETAG

    def test_fetch_error_keeps_previously_fetched_domains(
        self, fresh_validator: DisposableEmailValidator
    ) -> None:
        with mock.patch(
            "onyx.auth.disposable_email_validator.httpx.Client"
        ) as mock_client:
            client = mock_client.return_value.__enter__.return_value
            client.get.return_value = _response(
                200,
                json_body=["fetched-domain.example"],
                headers={"ETag": _ETAG},
            )
            fresh_validator.get_domains()

            fresh_validator._last_fetch_time = 0
            client.get.side_effect = httpx.ConnectError("network down")
            domains = fresh_validator.get_domains()

        assert "fetched-domain.example" in domains
        # Fallback domains stay included as well
        assert "trashlify.com" in domains

    def test_fetch_error_without_prior_fetch_returns_fallback(
        self, fresh_validator: DisposableEmailValidator
    ) -> None:
        with mock.patch(
            "onyx.auth.disposable_email_validator.httpx.Client"
        ) as mock_client:
            client = mock_client.return_value.__enter__.return_value
            client.get.side_effect = httpx.ConnectError("network down")
            domains = fresh_validator.get_domains()

        assert domains == fresh_validator._fallback_domains


class TestDisposableEmailValidator:
    """Test the DisposableEmailValidator class."""

    def test_singleton_pattern(self) -> None:
        """Test that DisposableEmailValidator is a singleton."""
        validator1 = DisposableEmailValidator()
        validator2 = DisposableEmailValidator()
        assert validator1 is validator2

    def test_fallback_domains_included(self) -> None:
        """Test that fallback domains are always included."""
        validator = DisposableEmailValidator()
        domains = validator.get_domains()

        # Check that our hardcoded fallback domains are present
        assert "trashlify.com" in domains
        assert "10minutemail.com" in domains
        assert "guerrillamail.com" in domains
        assert "mailinator.com" in domains
        assert "tempmail.com" in domains
        assert "throwaway.email" in domains
        assert "yopmail.com" in domains

    def test_is_disposable_trashlify(self) -> None:
        """Test that trashlify.com emails are detected as disposable."""
        assert is_disposable_email("test@trashlify.com") is True
        assert is_disposable_email("user123@trashlify.com") is True
        assert is_disposable_email("4q4k99yca1@trashlify.com") is True

    def test_is_disposable_other_known_domains(self) -> None:
        """Test detection of other known disposable domains."""
        disposable_emails = [
            "test@10minutemail.com",
            "user@guerrillamail.com",
            "temp@mailinator.com",
            "fake@tempmail.com",
            "throw@throwaway.email",
            "yop@yopmail.com",
        ]

        for email in disposable_emails:
            assert is_disposable_email(email) is True, f"{email} should be disposable"

    def test_is_not_disposable_legitimate_domains(self) -> None:
        """Test that legitimate email domains are not flagged."""
        legitimate_emails = [
            "user@gmail.com",
            "employee@company.com",
            "admin@onyx.app",
            "test@outlook.com",
            "person@yahoo.com",
            "contact@protonmail.com",
        ]

        for email in legitimate_emails:
            assert is_disposable_email(email) is False, (
                f"{email} should not be disposable"
            )

    def test_case_insensitive(self) -> None:
        """Test that domain checking is case-insensitive."""
        assert is_disposable_email("test@TRASHLIFY.COM") is True
        assert is_disposable_email("test@Trashlify.Com") is True
        assert is_disposable_email("test@TrAsHlIfY.cOm") is True

    def test_invalid_email_formats(self) -> None:
        """Test handling of invalid email formats."""
        assert is_disposable_email("") is False
        assert is_disposable_email("notanemail") is False
        assert is_disposable_email("@trashlify.com") is False
        assert is_disposable_email("test@") is False
        assert is_disposable_email("@") is False

    def test_email_with_subdomains(self) -> None:
        """Test that emails with subdomains are handled correctly."""
        # The domain should be the last part after @
        assert is_disposable_email("user@mail.trashlify.com") is False
        # Only exact domain matches should trigger

    def test_validator_instance_methods(self) -> None:
        """Test the validator instance methods directly."""
        validator = DisposableEmailValidator()

        # Test is_disposable method
        assert validator.is_disposable("test@trashlify.com") is True
        assert validator.is_disposable("test@gmail.com") is False

        # Test invalid inputs
        assert validator.is_disposable("") is False
        assert validator.is_disposable("invalid") is False
        assert validator.is_disposable("@trashlify.com") is False
