"""
A set of email domains kept in memory and refreshed from a remote list.

Shared by the disposable-domain and free-mail-domain checks at sign-up. Each
check subclasses this with its URL, its built-in domains and the parser for
the list's format.
"""

import threading
import time
from collections.abc import Callable, Iterable

import httpx

from onyx.utils.logger import setup_logger

logger = setup_logger()


class RemoteDomainBlocklist:
    """
    Thread-safe cache of a remote domain list.

    Fetches and caches the list. Refreshes are stale-while-revalidate:
    callers always get the cached set (or the built-in fallback before the
    first fetch completes) immediately, and a background thread updates the
    cache. Callers never wait on the network.
    """

    def __init__(
        self,
        *,
        name: str,
        url: str,
        fallback_domains: Iterable[str],
        parse: Callable[[httpx.Response], set[str]],
        cache_duration: float = 3600,
    ) -> None:
        # Used in log lines ("disposable email") and the refresh thread name.
        self._name = name
        self._url = url
        # Turns the response body into lowercased domains. Raises on a body
        # that is not the list; the last good set is kept then.
        self._parse = parse
        self._domains: set[str] = set()
        self._last_fetch_time: float = 0
        # HTTP cache validators from the last successful fetch. Used for
        # conditional requests so unchanged lists are not re-downloaded.
        self._etag: str | None = None
        self._last_modified: str | None = None
        # Guards check-and-set of the refresh thread so only one refresh
        # runs at a time. Never held during network calls.
        self._spawn_lock = threading.Lock()
        self._refresh_thread: threading.Thread | None = None
        self._cache_duration = cache_duration
        # Always included, so at least these are blocked when the fetch fails.
        self._fallback_domains = set(fallback_domains)

    def _should_refresh(self) -> bool:
        """Check if the cached domains should be refreshed."""
        return (time.time() - self._last_fetch_time) > self._cache_duration

    def _previous_or_fallback_domains(self) -> set[str]:
        """Return the last good set if one exists, else the built-in fallback."""
        if self._domains:
            return self._domains
        return self._fallback_domains.copy()

    def _fetch_domains(self) -> set[str]:
        """
        Fetch the domains from the configured URL.

        Sends a conditional request (If-None-Match / If-Modified-Since) when
        validators from a previous fetch are available. A 304 response keeps
        the cached set without downloading the full list again.

        Returns:
            Set of domain strings (lowercased)
        """
        if not self._url:
            logger.debug("No URL configured for %s domains", self._name)
            return self._fallback_domains.copy()

        headers: dict[str, str] = {}
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified

        try:
            logger.info("Fetching %s domains from %s", self._name, self._url)
            with httpx.Client(timeout=10.0) as client:
                response = client.get(self._url, headers=headers)

                if response.status_code == 304 and self._domains:
                    logger.info("%s domains unchanged (304)", self._name)
                    return self._domains

                response.raise_for_status()

                domains = self._parse(response)

                # Always include fallback domains
                domains.update(self._fallback_domains)

                self._etag = response.headers.get("ETag")
                self._last_modified = response.headers.get("Last-Modified")

                logger.info(
                    "Successfully fetched %s %s domains", len(domains), self._name
                )
                return domains

        except httpx.HTTPError as e:
            logger.warning("Failed to fetch %s domains (HTTP error): %s", self._name, e)
        except Exception as e:
            logger.warning("Failed to fetch %s domains: %s", self._name, e)

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
                name=f"{self._name.replace(' ', '-')}-domains-refresh",
                daemon=True,
            )
            self._refresh_thread = thread
            thread.start()
            return thread

    def get_domains(self) -> set[str]:
        """
        Get the cached set of domains.

        Stale-while-revalidate: a stale cache triggers a background
        refresh, and the current set is returned immediately. Before
        the first fetch completes, this is the built-in fallback set.

        Returns:
            Set of domain strings (lowercased)
        """
        if self._should_refresh():
            self._start_refresh()

        if self._domains:
            return self._domains.copy()
        return self._fallback_domains.copy()

    def refresh_now(self) -> None:
        """
        Fetch the list and wait for it.

        Normal refreshes run in the background when the cache is stale. This
        is for a caller that needs the new list before it goes on.
        """
        self._last_fetch_time = 0
        self._start_refresh().join()

    def contains_email_domain(self, email: str) -> bool:
        """Whether the email address's domain is in the list."""
        if not email or "@" not in email:
            return False

        parts = email.split("@")
        if len(parts) != 2 or not parts[0]:  # Must have user@domain with non-empty user
            return False

        domain = parts[1].lower().strip()
        if not domain:  # Domain part must not be empty
            return False

        return domain in self.get_domains()
