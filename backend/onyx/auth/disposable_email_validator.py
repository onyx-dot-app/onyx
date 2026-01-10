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

    Fetches and caches the list of disposable domains, with periodic refresh.
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
        self._fetch_lock = threading.Lock()
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

    def _fetch_domains(self) -> Set[str]:
        """
        Fetch disposable email domains from the configured URL.

        Returns:
            Set of domain strings (lowercased)
        """
        if not DISPOSABLE_EMAIL_DOMAINS_URL:
            logger.debug("DISPOSABLE_EMAIL_DOMAINS_URL not configured")
            return self._fallback_domains.copy()

        try:
            logger.info(
                f"Fetching disposable email domains from {DISPOSABLE_EMAIL_DOMAINS_URL}"
            )
            with httpx.Client(timeout=10.0) as client:
                response = client.get(DISPOSABLE_EMAIL_DOMAINS_URL)
                response.raise_for_status()

                domains_list = response.json()

                if not isinstance(domains_list, list):
                    logger.error(
                        f"Expected list from disposable domains URL, got {type(domains_list)}"
                    )
                    return self._fallback_domains.copy()

                # Convert all to lowercase and create set
                domains = {domain.lower().strip() for domain in domains_list if domain}

                # Always include fallback domains
                domains.update(self._fallback_domains)

                logger.info(
                    f"Successfully fetched {len(domains)} disposable email domains"
                )
                return domains

        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch disposable domains (HTTP error): {e}")
        except Exception as e:
            logger.warning(f"Failed to fetch disposable domains: {e}")

        # On error, return fallback domains
        return self._fallback_domains.copy()

    def get_domains(self) -> Set[str]:
        """
        Get the cached set of disposable email domains.
        Refreshes the cache if needed.

        Returns:
            Set of disposable domain strings (lowercased)
        """
        # Fast path: return cached domains if still fresh
        if self._domains and not self._should_refresh():
            return self._domains.copy()

        # Slow path: need to refresh
        with self._fetch_lock:
            # Double-check after acquiring lock
            if self._domains and not self._should_refresh():
                return self._domains.copy()

            self._domains = self._fetch_domains()
            self._last_fetch_time = time.time()
            return self._domains.copy()

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
    without waiting for the cache to expire.
    """
    _validator._last_fetch_time = 0
    _validator.get_domains()
