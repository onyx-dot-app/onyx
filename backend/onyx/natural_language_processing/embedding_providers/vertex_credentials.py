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
        self._lock = threading.Lock()

    def resolve(self, auth: VertexEmbeddingAuth) -> VertexEmbeddingCredentials:
        """Blocking: a miss can contact the GKE metadata server."""
        key = auth.credentials_key()
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached
        resolved = auth.resolve_credentials()
        with self._lock:
            winner = self._entries.setdefault(key, resolved)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return winner

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


VERTEX_CREDENTIALS = VertexCredentialsCache()
