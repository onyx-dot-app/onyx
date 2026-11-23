"""
A set of email domains kept in memory and refreshed from a remote list.

Shared by the disposable-domain and free-mail-domain checks at sign-up. Each
check configures this with its URL, its built-in domains and the parser for
the list's format.
"""

import threading
import time
from collections.abc import Callable, Iterable

import httpx

from onyx.utils.logger import setup_logger

logger = setup_logger()

# A fetched list with the HTTP validators that describe it.
_Fetched = tuple[set[str], str | None, str | None]


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
        # Monotonic time of the last refresh. None until the first one, and
        # again when a caller forces one.
        self._last_fetch_time: float | None = None
        # HTTP cache validators from the last successful fetch. Used for
        # conditional requests so unchanged lists are not re-downloaded.
        # Set together with `_domains`, never on their own.
        self._etag: str | None = None
        self._last_modified: str | None = None
        # Guards check-and-set of the refresh thread so only one refresh
        # runs at a time. Never held during network calls.
        self._spawn_lock = threading.Lock()
        self._refresh_thread: threading.Thread | None = None
        self._cache_duration = cache_duration
        # Always included, so at least these are blocked when the fetch fails.
        # Normalized the same way as the email domain they are compared with.
        self._fallback_domains = {d.strip().lower() for d in fallback_domains}

    def _should_refresh(self) -> bool:
        """Check if the cached domains should be refreshed."""
        if self._last_fetch_time is None:
            return True
        return (time.monotonic() - self._last_fetch_time) > self._cache_duration

    def _fetch_domains(self) -> _Fetched | None:
        """
        Fetch the domains from the configured URL.

        Sends a conditional request (If-None-Match / If-Modified-Since) when
        validators from a previous fetch are available.

        Returns:
            The new domains with the validators that describe them, or None
            when the cached set stays: the list is unchanged (304), or the
            fetch failed.
        """
        if not self._url:
            logger.debug("No URL configured for %s domains", self._name)
            return self._fallback_domains.copy(), None, None

        headers: dict[str, str] = {}
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified

        try:
            logger.info("Fetching %s domains from %s", self._name, self._url)
            with httpx.Client(timeout=10.0) as client:
                response = client.get(self._url, headers=headers)

            # Validators are only sent after a successful fetch, so a 304 in
            # answer to them means the cached set is current, even when empty.
            if response.status_code == 304 and headers:
                logger.info("%s domains unchanged (304)", self._name)
                return None

            response.raise_for_status()

            # A copy: the parser's set must not become the cache.
            domains = set(self._parse(response))
            domains.update(self._fallback_domains)

            logger.info("Successfully fetched %s %s domains", len(domains), self._name)
            return (
                domains,
                response.headers.get("ETag"),
                response.headers.get("Last-Modified"),
            )

        except httpx.HTTPError as e:
            logger.warning("Failed to fetch %s domains (HTTP error): %s", self._name, e)
        except Exception as e:
            logger.warning("Failed to fetch %s domains: %s", self._name, e)

        # On error, keep the last good set (or the fallback if none exists)
        return None

    def _refresh(self) -> None:
        """Fetch the list and swap the cache. Runs on the refresh thread."""
        fetched = self._fetch_domains()
        if fetched is not None:
            self._domains, self._etag, self._last_modified = fetched
        self._last_fetch_time = time.monotonic()

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
        self._last_fetch_time = None
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
