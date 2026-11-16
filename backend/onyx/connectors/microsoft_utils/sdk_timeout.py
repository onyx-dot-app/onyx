"""A read timeout for the office365 SDK's HTTP calls.

``ClientRequest.execute_request_direct`` in Office365-REST-Python-Client calls
``requests.get``, ``post``, ``patch``, ``put`` and ``delete`` without a
``timeout``, and ``RequestOptions`` has no field to set one. A connection that
the network drops without a reset (an idle-timeout on a firewall or NAT) then
blocks the calling thread forever, with no CPU use, and the indexing attempt
stays ``IN_PROGRESS`` indefinitely. Retries cannot help: they only run when an
exception is raised.

:func:`bound_sdk_requests` replaces ``execute_request_direct`` on one SDK
context with the same request carrying a timeout. A hang then raises
``requests.exceptions.Timeout``, which the callers' retry layer already treats
as transient.
"""

from typing import Any

import requests
from office365.runtime.client_request import ClientRequest
from office365.runtime.client_runtime_context import ClientRuntimeContext
from office365.runtime.http.http_method import HttpMethod
from office365.runtime.http.request_options import RequestOptions


def _send_with_timeout(
    request: RequestOptions, timeout: float | tuple[float, float]
) -> requests.Response:
    """Sends ``request`` the way the SDK does, plus a timeout."""
    kwargs: dict[str, Any] = {
        "url": request.url,
        "headers": request.headers,
        "auth": request.auth,
        "verify": request.verify,
        "proxies": request.proxies,
    }
    method: str = request.method
    if method == HttpMethod.Post:
        if request.is_bytes or request.is_file:
            kwargs["data"] = request.data
        else:
            kwargs["json"] = request.data
    elif method == HttpMethod.Patch:
        kwargs["json"] = request.data
    elif method == HttpMethod.Put:
        kwargs["data"] = request.data
    elif method == HttpMethod.Delete:
        pass
    else:
        method = HttpMethod.Get
        kwargs["stream"] = request.stream
    response: requests.Response = requests.request(method, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response


def bound_sdk_requests(
    context: ClientRuntimeContext, timeout: float | tuple[float, float]
) -> ClientRuntimeContext:
    """Gives every HTTP call made through ``context`` a timeout.

    ``timeout`` is a ``requests`` timeout: seconds, or ``(connect, read)``.
    Returns ``context`` so a client can be built and bound in one expression.
    """
    pending: ClientRequest = context.pending_request()

    def execute_request_direct(request: RequestOptions) -> requests.Response:
        pending.beforeExecute.notify(request)
        return _send_with_timeout(request, timeout)

    pending.execute_request_direct = execute_request_direct  # type: ignore[method-assign]
    return context
