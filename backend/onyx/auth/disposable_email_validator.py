"""
Utility to validate and block disposable/temporary email addresses.

This module fetches a list of known disposable email domains from a remote source
and caches them for performance. It's used during user registration to prevent
abuse from temporary email services.
"""

import threading
import time
from typing import Set

import httpx

from onyx.configs.app_configs import DISPOSABLE_EMAIL_DOMAINS_URL
from onyx.utils.logger import setup_logger

logger = setup_logger()


class DisposableEmailValidator:
    """
    Thread-safe singleton validator for disposable email domains.

    Fetches and caches the list of disposable domains. Refreshes are
    stale-while-revalidate: callers always get the cached set (or the
    hardcoded fallback before the first fetch completes) immediately,
    and a background thread updates the cache. Callers never wait on
    the network.
    """

    _instance: "DisposableEmailValidator | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "DisposableEmailValidator":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # Check if already initialized using a try/except to avoid type issues
        try:
            if self._initialized:
                return
        except AttributeError:
            pass

        self._domains: Set[str] = set()
        self._last_fetch_time: float = 0
        # HTTP cache validators from the last successful fetch. Used for
        # conditional requests so unchanged lists are not re-downloaded.
        self._etag: str | None = None
        self._last_modified: str | None = None
        # Guards check-and-set of the refresh thread so only one refresh
        # runs at a time. Never held during network calls.
        self._spawn_lock = threading.Lock()
        self._refresh_thread: threading.Thread | None = None
        # Cache for 1 hour
        self._cache_duration = 3600
        # Hardcoded fallback list of common disposable domains
        # This ensures we block at least these even if the remote fetch fails
        self._fallback_domains = {
            "trashlify.com",
            "10minutemail.com",
            "guerrillamail.com",
            "mailinator.com",
            "tempmail.com",
            "chat-tempmail.com",
            "throwaway.email",
            "yopmail.com",
            "temp-mail.org",
            "getnada.com",
            "maildrop.cc",
        }
        # Set initialized flag last to prevent race conditions
        self._initialized: bool = True

    def _should_refresh(self) -> bool:
        """Check if the cached domains should be refreshed."""
        return (time.time() - self._last_fetch_time) > self._cache_duration

    def _previous_or_fallback_domains(self) -> Set[str]:
        """Return the last good set if one exists, else the hardcoded fallback."""
        if self._domains:
            return self._domains
        return self._fallback_domains.copy()

    def _fetch_domains(self) -> Set[str]:
        """
        Fetch disposable email domains from the configured URL.

        Sends a conditional request (If-None-Match / If-Modified-Since) when
        validators from a previous fetch are available. A 304 response keeps
        the cached set without downloading the full list again.

        Returns:
            Set of domain strings (lowercased)
        """
        if not DISPOSABLE_EMAIL_DOMAINS_URL:
            logger.debug("DISPOSABLE_EMAIL_DOMAINS_URL not configured")
            return self._fallback_domains.copy()

        headers: dict[str, str] = {}
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified

        try:
            logger.info(
                "Fetching disposable email domains from %s",
                DISPOSABLE_EMAIL_DOMAINS_URL,
            )
            with httpx.Client(timeout=10.0) as client:
                response = client.get(DISPOSABLE_EMAIL_DOMAINS_URL, headers=headers)

                if response.status_code == 304 and self._domains:
                    logger.info("Disposable email domains unchanged (304)")
                    return self._domains

                response.raise_for_status()

                domains_list = response.json()

                if not isinstance(domains_list, list):
                    logger.error(
                        "Expected list from disposable domains URL, got %s",
                        type(domains_list),
                    )
                    return self._previous_or_fallback_domains()

                # Convert all to lowercase and create set
                domains = {domain.lower().strip() for domain in domains_list if domain}

                # Always include fallback domains
                domains.update(self._fallback_domains)

                self._etag = response.headers.get("ETag")
                self._last_modified = response.headers.get("Last-Modified")

                logger.info(
                    "Successfully fetched %s disposable email domains", len(domains)
                )
                return domains

        except httpx.HTTPError as e:
            logger.warning("Failed to fetch disposable domains (HTTP error): %s", e)
        except Exception as e:
            logger.warning("Failed to fetch disposable domains: %s", e)

        # On error, keep the last good set (or the fallback if none exists)
        return self._previous_or_fallback_domains()

    def _refresh(self) -> None:
        """Fetch the list and swap the cache. Runs on the refresh thread."""
        domains = self._fetch_domains()
        self._domains = domains
        self._last_fetch_time = time.time()

    def _start_refresh(self) -> threading.Thread:
        """
        Start a background refresh unless one is already running.

        Returns:
            The running (or just-started) refresh thread
        """
        with self._spawn_lock:
            thread = self._refresh_thread
            if thread is not None:
                if thread.is_alive():
                    return thread
                # Re-check staleness under the lock: a refresh may have
                # completed after the caller decided one was needed
                if not self._should_refresh():
                    return thread
            thread = threading.Thread(
                target=self._refresh,
                name="disposable-email-domains-refresh",
                daemon=True,
            )
            self._refresh_thread = thread
            thread.start()
            return thread

    def get_domains(self) -> Set[str]:
        """
        Get the cached set of disposable email domains.

        Stale-while-revalidate: a stale cache triggers a background
        refresh, and the current set is returned immediately. Before
        the first fetch completes, this is the hardcoded fallback set.

        Returns:
            Set of disposable domain strings (lowercased)
        """
        if self._should_refresh():
            self._start_refresh()

        if self._domains:
            return self._domains.copy()
        return self._fallback_domains.copy()

    def is_disposable(self, email: str) -> bool:
        """
        Check if an email address uses a disposable domain.

        Args:
            email: The email address to check

        Returns:
            True if the email domain is disposable, False otherwise
        """
        if not email or "@" not in email:
            return False

        parts = email.split("@")
        if len(parts) != 2 or not parts[0]:  # Must have user@domain with non-empty user
            return False

        domain = parts[1].lower().strip()
        if not domain:  # Domain part must not be empty
            return False

        disposable_domains = self.get_domains()
        return domain in disposable_domains


# Global singleton instance
_validator = DisposableEmailValidator()


def is_disposable_email(email: str) -> bool:
    """
    Check if an email address uses a disposable/temporary domain.

    This is a convenience function that uses the global validator instance.

    Args:
        email: The email address to check

    Returns:
        True if the email uses a disposable domain, False otherwise
    """
    return _validator.is_disposable(email)


def refresh_disposable_domains() -> None:
    """
    Force a refresh of the disposable domains list.

    This can be called manually if you want to update the list
    without waiting for the cache to expire. Unlike normal cache
    expiry, this blocks until the refresh completes.
    """
    _validator._last_fetch_time = 0
    _validator._start_refresh().join()
