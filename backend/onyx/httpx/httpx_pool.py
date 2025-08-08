import threading
from typing import Any

import httpx


def make_default_kwargs() -> dict[str, Any]:
    return {
        "http2": True,
        "limits": httpx.Limits(),
    }


class HttpxPool:
    """Class to manage a global httpx Client instance"""

    _clients: dict[str, httpx.Client] = {}
    _lock: threading.Lock = threading.Lock()

    # Default parameters for creation

    def __init__(self) -> None:
        pass

    @classmethod
    def _init_client(cls, **kwargs: Any) -> httpx.Client:
        """Private helper method to create and return an httpx.Client."""
        merged_kwargs = {**(make_default_kwargs()), **kwargs}
        return httpx.Client(**merged_kwargs)

    @classmethod
    def init_client(cls, name: str, **kwargs: Any) -> None:
        """Allow the caller to init the client with extra params."""
        with cls._lock:
            if name not in cls._clients:
                cls._clients[name] = cls._init_client(**kwargs)

    @classmethod
    def close_client(cls, name: str) -> None:
        """Allow the caller to close the client."""
        with cls._lock:
            client = cls._clients.pop(name, None)
            if client:
                client.close()

    @classmethod
    def close_all(cls) -> None:
        """Close all registered clients."""
        with cls._lock:
            for client in cls._clients.values():
                client.close()
            cls._clients.clear()

    @classmethod
    def get(cls, name: str) -> httpx.Client:
        """Gets the httpx.Client. Will init to default settings if not init'd."""
        with cls._lock:
            if name not in cls._clients:
                cls._clients[name] = cls._init_client()
            return cls._clients[name]
