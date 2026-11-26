import threading
from collections import OrderedDict

from onyx.natural_language_processing.embedding_auth import VertexEmbeddingAuth
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingCredentials

# Each resolve signs a new token request. google-auth refreshes expired tokens,
# so one credentials object can serve the process.


class VertexCredentialsCache:
    def __init__(self, max_entries: int = 32) -> None:
        if max_entries < 1:
            raise ValueError("Need max_entries >= 1.")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, VertexEmbeddingCredentials] = OrderedDict()
        # One lock per key that a thread resolves now.
        self._resolving: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def resolve(self, auth: VertexEmbeddingAuth) -> VertexEmbeddingCredentials:
        """Blocking: a miss can contact the GKE metadata server."""
        key = auth.credentials_key()
        with self._lock:
            cached = self._get_locked(key)
            if cached is not None:
                return cached
            resolving = self._resolving.setdefault(key, threading.Lock())
        # One thread resolves a key. The others wait here and use its result.
        with resolving:
            with self._lock:
                cached = self._get_locked(key)
                if cached is not None:
                    return cached
            try:
                resolved = auth.resolve_credentials()
            except BaseException:
                # A failure is not cached, so the next call resolves again.
                with self._lock:
                    self._resolving.pop(key, None)
                raise
            # One step, so a new caller finds either the entry or the lock.
            with self._lock:
                self._entries[key] = resolved
                self._resolving.pop(key, None)
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
            return resolved

    def _get_locked(self, key: str) -> VertexEmbeddingCredentials | None:
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
        return cached

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


VERTEX_CREDENTIALS = VertexCredentialsCache()
