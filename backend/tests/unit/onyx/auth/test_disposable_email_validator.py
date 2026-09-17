"""
Tests for disposable email validation.
"""

import threading
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


def _refresh_and_get(validator: DisposableEmailValidator) -> set[str]:
    """Force a refresh, run it to completion, and return the domains."""
    validator._last_fetch_time = 0
    thread = validator._start_refresh()
    thread.join(timeout=5)
    assert not thread.is_alive()
    return validator.get_domains()


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

            domains = _refresh_and_get(fresh_validator)

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
            _refresh_and_get(fresh_validator)

            # Answer the next refresh with a 304
            client.get.return_value = _response(304)
            domains = _refresh_and_get(fresh_validator)

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
            _refresh_and_get(fresh_validator)

            client.get.side_effect = httpx.ConnectError("network down")
            domains = _refresh_and_get(fresh_validator)

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
            domains = _refresh_and_get(fresh_validator)

        assert domains == fresh_validator._fallback_domains


class TestStaleWhileRevalidate:
    """Test that callers never wait on the network for a refresh."""

    def test_stale_cache_is_served_while_refresh_runs(
        self, fresh_validator: DisposableEmailValidator
    ) -> None:
        with mock.patch(
            "onyx.auth.disposable_email_validator.httpx.Client"
        ) as mock_client:
            client = mock_client.return_value.__enter__.return_value
            client.get.return_value = _response(
                200, json_body=["old-domain.example"], headers={"ETag": _ETAG}
            )
            _refresh_and_get(fresh_validator)

            release = threading.Event()

            def slow_get(*_args: object, **_kwargs: object) -> httpx.Response:
                assert release.wait(timeout=5)
                return _response(200, json_body=["new-domain.example"])

            client.get.side_effect = slow_get

            # Expire the cache: the next call must return the stale set
            # immediately while the refresh runs in the background
            fresh_validator._last_fetch_time = 0
            stale = fresh_validator.get_domains()
            assert "old-domain.example" in stale
            assert "new-domain.example" not in stale

            thread = fresh_validator._refresh_thread
            assert thread is not None
            assert thread.is_alive()

            release.set()
            thread.join(timeout=5)
            assert not thread.is_alive()

            assert "new-domain.example" in fresh_validator.get_domains()

    def test_cold_start_returns_fallback_and_shares_one_refresh(
        self, fresh_validator: DisposableEmailValidator
    ) -> None:
        with mock.patch(
            "onyx.auth.disposable_email_validator.httpx.Client"
        ) as mock_client:
            client = mock_client.return_value.__enter__.return_value

            release = threading.Event()

            def slow_get(*_args: object, **_kwargs: object) -> httpx.Response:
                assert release.wait(timeout=5)
                return _response(200, json_body=["fetched-domain.example"])

            client.get.side_effect = slow_get

            # Both calls return the fallback immediately; the second call
            # must not start a second refresh
            first = fresh_validator.get_domains()
            second = fresh_validator.get_domains()
            assert first == fresh_validator._fallback_domains
            assert second == fresh_validator._fallback_domains

            thread = fresh_validator._refresh_thread
            assert thread is not None

            release.set()
            thread.join(timeout=5)
            assert not thread.is_alive()

            assert client.get.call_count == 1
            assert "fetched-domain.example" in fresh_validator.get_domains()

    def test_no_redundant_refresh_when_cache_became_fresh(
        self, fresh_validator: DisposableEmailValidator
    ) -> None:
        with mock.patch(
            "onyx.auth.disposable_email_validator.httpx.Client"
        ) as mock_client:
            client = mock_client.return_value.__enter__.return_value
            client.get.return_value = _response(
                200, json_body=["fetched-domain.example"], headers={"ETag": _ETAG}
            )
            _refresh_and_get(fresh_validator)
            assert client.get.call_count == 1

            # A caller that saw a stale cache before this refresh finished
            # must not trigger a second fetch now that the cache is fresh
            thread = fresh_validator._start_refresh()
            thread.join(timeout=5)
            assert client.get.call_count == 1


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
