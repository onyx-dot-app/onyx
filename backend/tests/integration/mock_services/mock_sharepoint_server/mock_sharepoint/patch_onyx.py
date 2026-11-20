"""Points the Microsoft calls of a process at the mock server. Test code only:
Onyx has no setting for this.

MSAL, the office365 SDK and Onyx's own Graph calls all send through
``requests``. This module patches two things:

- ``requests.Session.send``: a request to ``graph.microsoft.com``,
  ``login.microsoftonline.com`` or a ``*.sharepoint.com`` host goes to the
  mock, under ``/graph``, ``/login`` or ``/sharepoint/<host>``. The path, the
  query and the headers stay as they are. The mock writes the real hosts in
  its links, so Onyx's URL checks see what they see with Microsoft.
- ``socket.getaddrinfo``: a ``*.sharepoint.com`` name gets a fixed public
  address with no lookup, because the outbound URL guard resolves a site URL
  and the mock tenant has no DNS record.

In a test, use ``point_onyx_at_mock`` as a context manager. For a running
Onyx, ``sitecustomize.py`` in the parent directory calls
``install_for_process`` when ``MOCK_SHAREPOINT_URL`` is set.

Only the commercial cloud hosts are redirected. This module does not import
Onyx, so a process can load it before Onyx.
"""

import functools
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock
from urllib.parse import urlsplit

import requests

GRAPH_HOST = "graph.microsoft.com"
LOGIN_HOST = "login.microsoftonline.com"
SHAREPOINT_SUFFIX = ".sharepoint.com"
# A public address of SharePoint Online. Nothing connects to it: the redirect
# sends the traffic to the mock.
_SHAREPOINT_ADDRESS = "13.107.136.10"


def _base(url: str) -> str:
    return url.rstrip("/")


def mock_url_for(url: str, base: str) -> str | None:
    """The mock URL for a Microsoft URL. None for any other URL."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == GRAPH_HOST:
        prefix = "/graph"
    elif host == LOGIN_HOST:
        prefix = "/login"
    elif host.endswith(SHAREPOINT_SUFFIX):
        prefix = f"/sharepoint/{host}"
    else:
        return None
    query = f"?{parts.query}" if parts.query else ""
    return f"{base}{prefix}{parts.path}{query}"


class _RedirectedSend:
    """``requests.Session.send`` with the Microsoft hosts sent to the mock."""

    def __init__(self, current: Callable[..., requests.Response], base: str) -> None:
        # Wrap the real method, not an earlier redirect, so the newest patch
        # selects the URL.
        self.original: Callable[..., requests.Response] = (
            current.original if isinstance(current, _RedirectedSend) else current
        )
        self.base = base

    def __get__(
        self, instance: requests.Session | None, owner: type | None = None
    ) -> Any:
        if instance is None:
            return self
        return functools.partial(self, instance)

    def __call__(
        self,
        session: requests.Session,
        request: requests.PreparedRequest,
        **kwargs: Any,
    ) -> requests.Response:
        target = mock_url_for(request.url or "", self.base)
        if target is not None:
            request.url = target
            # The proxy settings were read for the Microsoft host. The mock
            # is reached without a proxy.
            kwargs["proxies"] = {}
        return self.original(session, request, **kwargs)


class _SharepointDns:
    """``socket.getaddrinfo`` that answers ``*.sharepoint.com`` names itself."""

    def __init__(self, current: Callable[..., list[Any]]) -> None:
        self.original: Callable[..., list[Any]] = (
            current.original if isinstance(current, _SharepointDns) else current
        )

    def __call__(self, host: Any, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
        name = host.decode() if isinstance(host, bytes) else host
        if isinstance(name, str) and name.lower().endswith(SHAREPOINT_SUFFIX):
            return self.original(_SHAREPOINT_ADDRESS, port, *args, **kwargs)
        return self.original(host, port, *args, **kwargs)


@contextmanager
def point_onyx_at_mock(mock_url: str) -> Iterator[None]:
    """Sends the Microsoft calls of this process to the mock at ``mock_url``
    until the block ends."""
    send = _RedirectedSend(requests.Session.send, _base(mock_url))
    dns = _SharepointDns(socket.getaddrinfo)
    with (
        mock.patch.object(requests.Session, "send", send),
        mock.patch.object(socket, "getaddrinfo", dns),
    ):
        yield


def install_for_process(mock_url: str) -> None:
    """Sends the Microsoft calls of this process to the mock for its whole
    life."""
    requests.Session.send = _RedirectedSend(  # ty: ignore[invalid-assignment]
        requests.Session.send, _base(mock_url)
    )
    socket.getaddrinfo = _SharepointDns(  # ty: ignore[invalid-assignment]
        socket.getaddrinfo
    )
