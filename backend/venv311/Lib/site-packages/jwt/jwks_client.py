from __future__ import annotations

import json
import urllib.request
from functools import lru_cache
from ssl import SSLContext
from typing import Any
from urllib.error import HTTPError, URLError

from .api_jwk import PyJWK, PyJWKSet
from .api_jwt import decode_complete as decode_token
from .exceptions import PyJWKClientConnectionError, PyJWKClientError
from .jwk_set_cache import JWKSetCache


class PyJWKClient:
    def __init__(
        self,
        uri: str,
        cache_keys: bool = False,
        max_cached_keys: int = 16,
        cache_jwk_set: bool = True,
        lifespan: float = 300,
        headers: dict[str, Any] | None = None,
        timeout: float = 30,
        ssl_context: SSLContext | None = None,
    ):
        """A client for retrieving signing keys from a JWKS endpoint.

        ``PyJWKClient`` uses a two-tier caching system to avoid unnecessary
        network requests:

        **Tier 1 — JWK Set cache** (enabled by default):
        Caches the entire JSON Web Key Set response from the endpoint.
        Controlled by:

        - ``cache_jwk_set``: Set to ``True`` (the default) to enable this
          cache. When enabled, the JWK Set is fetched from the network only
          when the cache is empty or expired.
        - ``lifespan``: Time in seconds before the cached JWK Set expires.
          Defaults to ``300`` (5 minutes). Must be greater than 0.

        **Tier 2 — Signing key cache** (disabled by default):
        Caches individual signing keys (looked up by ``kid``) using an LRU
        cache with **no time-based expiration**. Keys are evicted only when
        the cache reaches its maximum size. Controlled by:

        - ``cache_keys``: Set to ``True`` to enable this cache.
          Defaults to ``False``.
        - ``max_cached_keys``: Maximum number of signing keys to keep in
          the LRU cache. Defaults to ``16``.

        :param uri: The URL of the JWKS endpoint.
        :type uri: str
        :param cache_keys: Enable the per-key LRU cache (Tier 2).
        :type cache_keys: bool
        :param max_cached_keys: Max entries in the signing key LRU cache.
        :type max_cached_keys: int
        :param cache_jwk_set: Enable the JWK Set response cache (Tier 1).
        :type cache_jwk_set: bool
        :param lifespan: TTL in seconds for the JWK Set cache.
        :type lifespan: float
        :param headers: Optional HTTP headers to include in requests.
        :type headers: dict or None
        :param timeout: HTTP request timeout in seconds.
        :type timeout: float
        :param ssl_context: Optional SSL context for the request.
        :type ssl_context: ssl.SSLContext or None
        """
        if headers is None:
            headers = {}
        self.uri = uri
        self.jwk_set_cache: JWKSetCache | None = None
        self.headers = headers
        self.timeout = timeout
        self.ssl_context = ssl_context

        if cache_jwk_set:
            # Init jwt set cache with default or given lifespan.
            # Default lifespan is 300 seconds (5 minutes).
            if lifespan <= 0:
                raise PyJWKClientError(
                    f'Lifespan must be greater than 0, the input is "{lifespan}"'
                )
            self.jwk_set_cache = JWKSetCache(lifespan)
        else:
            self.jwk_set_cache = None

        if cache_keys:
            # Cache signing keys
            get_signing_key = lru_cache(maxsize=max_cached_keys)(self.get_signing_key)
            # Ignore mypy (https://github.com/python/mypy/issues/2427)
            self.get_signing_key = get_signing_key  # type: ignore[method-assign]

    def fetch_data(self) -> Any:
        """Fetch the JWK Set from the JWKS endpoint.

        Makes an HTTP request to the configured ``uri`` and returns the
        parsed JSON response. If the JWK Set cache is enabled, the
        response is stored in the cache.

        :returns: The parsed JWK Set as a dictionary.
        :raises PyJWKClientConnectionError: If the HTTP request fails.
        """
        jwk_set: Any = None
        try:
            r = urllib.request.Request(url=self.uri, headers=self.headers)
            with urllib.request.urlopen(
                r, timeout=self.timeout, context=self.ssl_context
            ) as response:
                jwk_set = json.load(response)
        except (URLError, TimeoutError) as e:
            if isinstance(e, HTTPError):
                e.close()
            raise PyJWKClientConnectionError(
                f'Fail to fetch data from the url, err: "{e}"'
            ) from e
        else:
            return jwk_set
        finally:
            if self.jwk_set_cache is not None:
                self.jwk_set_cache.put(jwk_set)

    def get_jwk_set(self, refresh: bool = False) -> PyJWKSet:
        """Return the JWK Set, using the cache when available.

        :param refresh: Force a fresh fetch from the endpoint, bypassing
            the cache.
        :type refresh: bool
        :returns: The JWK Set.
        :rtype: PyJWKSet
        :raises PyJWKClientError: If the endpoint does not return a JSON
            object.
        """
        data = None
        if self.jwk_set_cache is not None and not refresh:
            data = self.jwk_set_cache.get()

        if data is None:
            data = self.fetch_data()

        if not isinstance(data, dict):
            raise PyJWKClientError("The JWKS endpoint did not return a JSON object")

        return PyJWKSet.from_dict(data)

    def get_signing_keys(self, refresh: bool = False) -> list[PyJWK]:
        """Return all signing keys from the JWK Set.

        Filters the JWK Set to keys whose ``use`` is ``"sig"`` (or
        unspecified) and that have a ``kid``.

        :param refresh: Force a fresh fetch from the endpoint, bypassing
            the cache.
        :type refresh: bool
        :returns: A list of signing keys.
        :rtype: list[PyJWK]
        :raises PyJWKClientError: If no signing keys are found.
        """
        jwk_set = self.get_jwk_set(refresh)
        signing_keys = [
            jwk_set_key
            for jwk_set_key in jwk_set.keys
            if jwk_set_key.public_key_use in ["sig", None] and jwk_set_key.key_id
        ]

        if not signing_keys:
            raise PyJWKClientError("The JWKS endpoint did not contain any signing keys")

        return signing_keys

    def get_signing_key(self, kid: str) -> PyJWK:
        """Return the signing key matching the given ``kid``.

        If no match is found in the current JWK Set, the set is
        refreshed from the endpoint and the lookup is retried once.

        :param kid: The key ID to look up.
        :type kid: str
        :returns: The matching signing key.
        :rtype: PyJWK
        :raises PyJWKClientError: If no matching key is found after
            refreshing.
        """
        signing_keys = self.get_signing_keys()
        signing_key = self.match_kid(signing_keys, kid)

        if not signing_key:
            # If no matching signing key from the jwk set, refresh the jwk set and try again.
            signing_keys = self.get_signing_keys(refresh=True)
            signing_key = self.match_kid(signing_keys, kid)

            if not signing_key:
                raise PyJWKClientError(
                    f'Unable to find a signing key that matches: "{kid}"'
                )

        return signing_key

    def get_signing_key_from_jwt(self, token: str | bytes) -> PyJWK:
        """Return the signing key for a JWT by reading its ``kid`` header.

        Extracts the ``kid`` from the token's unverified header and
        delegates to :meth:`get_signing_key`.

        :param token: The encoded JWT.
        :type token: str or bytes
        :returns: The matching signing key.
        :rtype: PyJWK
        """
        unverified = decode_token(token, options={"verify_signature": False})
        header = unverified["header"]
        return self.get_signing_key(header.get("kid"))

    @staticmethod
    def match_kid(signing_keys: list[PyJWK], kid: str) -> PyJWK | None:
        """Find a key in *signing_keys* that matches *kid*.

        :param signing_keys: The list of keys to search.
        :type signing_keys: list[PyJWK]
        :param kid: The key ID to match.
        :type kid: str
        :returns: The matching key, or ``None`` if not found.
        :rtype: PyJWK or None
        """
        signing_key = None

        for key in signing_keys:
            if key.key_id == kid:
                signing_key = key
                break

        return signing_key
