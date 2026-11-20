"""Paces the calls of a Microsoft connector to Graph and SharePoint REST.

Microsoft counts resource units (RU) for each app registration in a tenant.
Each call type has a cost. The pacer takes the cost of a call from the shared
source-API limiter before the call goes out. When Microsoft answers 429 or
503, the pacer reports the refusal, and reports the Retry-After time so that
every thread of every worker on the app waits.

The pacer also names the client. Microsoft gives priority to traffic with a
User-Agent of the form ``ISV|<company>|<app>/<version>``.

A connector with no limiter has no pacer. Its calls go out as before, with
the User-Agent.
"""

import re
import threading
import weakref
from collections.abc import Callable
from enum import Enum

from office365.runtime.client_object import ClientObject
from office365.runtime.client_runtime_context import ClientRuntimeContext
from office365.runtime.http.request_options import RequestOptions
from office365.runtime.queries.client_query import ClientQuery

from onyx import __version__
from onyx.connectors.cross_connector_utils.server_wait import bound_server_wait
from onyx.connectors.interfaces import SourceApiLimiter
from onyx.utils.retry_after import parse_retry_after_seconds

# The one budget of an app registration. Graph and SharePoint REST calls
# count toward the same limit.
GRAPH_LIMITER_API = "graph"

USER_AGENT_HEADER = "User-Agent"
MICROSOFT_USER_AGENT = f"ISV|Onyx|Onyx/{__version__}"

_THROTTLE_STATUSES: frozenset[int] = frozenset({429, 503})
_RATE_LIMIT_STATUS = 429
_SERVER_WAIT_SOURCE = "microsoft_graph"


class MicrosoftCall(str, Enum):
    """The call types that Microsoft gives a cost in resource units."""

    # One item, site, drive or page by id or path.
    ITEM_GET = "item_get"
    # One page of a drive delta.
    DELTA_PAGE = "delta_page"
    # One page of a folder's children.
    CHILDREN_PAGE = "children_page"
    # The content of one file.
    DOWNLOAD = "download"
    # A Graph call that reads permissions.
    PERMISSION = "permission"
    # A SharePoint REST call. Microsoft publishes no cost for REST.
    REST = "rest"
    # A list page or another read with no published cost of its own.
    OTHER = "other"


RU_COSTS: dict[MicrosoftCall, int] = {
    MicrosoftCall.ITEM_GET: 1,
    MicrosoftCall.DELTA_PAGE: 1,
    MicrosoftCall.CHILDREN_PAGE: 2,
    MicrosoftCall.DOWNLOAD: 1,
    MicrosoftCall.PERMISSION: 5,
    # The start estimate: a permission read is the usual REST call.
    MicrosoftCall.REST: 5,
    MicrosoftCall.OTHER: 1,
}


_DRIVE_ITEM_PATH = re.compile(r"/drives/[^/]+/(items/[^/]+|root(:/.+)?)$")
_SITE_PAGE_PATH = re.compile(
    r"/sites/[^/]+/pages/(?!microsoft\.graph\.)[^/]+(/microsoft\.graph\.sitepage)?$"
)


def graph_call_type(url: str) -> MicrosoftCall:
    """The call type of a Graph request, from its URL. One table for the raw
    requests and the requests that the office365 SDK builds, so a new call
    site cannot go out with no cost."""
    path = url.split("?", 1)[0].rstrip("/").lower()
    if path.endswith("/permissions") or "/permissions/" in path:
        return MicrosoftCall.PERMISSION
    if path.endswith("/children"):
        return MicrosoftCall.CHILDREN_PAGE
    if path.endswith("/delta"):
        return MicrosoftCall.DELTA_PAGE
    if path.endswith(("/content", "/$value")):
        return MicrosoftCall.DOWNLOAD
    if _DRIVE_ITEM_PATH.search(path) or _SITE_PAGE_PATH.search(path):
        return MicrosoftCall.ITEM_GET
    return MicrosoftCall.OTHER


class MicrosoftRequestPacer:
    """Takes the cost of each call from the limiter, and reports refusals."""

    def __init__(self, limiter: SourceApiLimiter) -> None:
        self._limiter = limiter

    def acquire(self, call: MicrosoftCall) -> None:
        """Waits until the call fits the app's budget and no pause is on.
        Call it before each try of a request."""
        self._limiter.acquire(GRAPH_LIMITER_API, RU_COSTS[call])

    def report_response(self, status: int | None, retry_after: str | None) -> None:
        """Reports a 429 or 503 answer. Call it from the thread that sent the
        request, before the retry wait."""
        if status not in _THROTTLE_STATUSES:
            return
        seconds = parse_retry_after_seconds(retry_after)
        if seconds is not None and seconds > 0:
            self._limiter.report_retry_after(
                GRAPH_LIMITER_API,
                bound_server_wait(seconds, _SERVER_WAIT_SOURCE, classify=False),
            )
        if status == _RATE_LIMIT_STATUS:
            self._limiter.report_rate_limit(GRAPH_LIMITER_API, None, user_scope=False)


# The pacer of each SDK client, so that the retry loop can report a refusal
# of a query from the query's client.
PacerSource = Callable[[], MicrosoftRequestPacer | None]
_client_pacers: "weakref.WeakKeyDictionary[ClientRuntimeContext, PacerSource]" = (
    weakref.WeakKeyDictionary()
)
_client_pacers_lock = threading.Lock()


def prepare_sdk_client[C: ClientRuntimeContext](
    client: C,
    get_pacer: PacerSource,
    call: MicrosoftCall | None = None,
) -> C:
    """Makes every request of an office365 SDK client carry the User-Agent
    and, with a pacer, take its cost first. ``get_pacer`` is read for each
    request, because a connector gets its limiter after its credentials.
    ``call`` is the type of every request of the client. None reads the type
    from each request URL."""

    def before_request(request: RequestOptions) -> None:
        request.headers[USER_AGENT_HEADER] = MICROSOFT_USER_AGENT
        pacer = get_pacer()
        if pacer is not None:
            pacer.acquire(call or graph_call_type(request.url))

    client.before_execute(before_request, once=False)
    with _client_pacers_lock:
        _client_pacers[client] = get_pacer
    return client


def sdk_query_pacer(query: object) -> MicrosoftRequestPacer | None:
    """The pacer of the client that an SDK query runs on, if the client is
    from ``prepare_sdk_client`` and has one."""
    if not isinstance(query, (ClientQuery, ClientObject)):
        return None
    with _client_pacers_lock:
        get_pacer = _client_pacers.get(query.context)
    return get_pacer() if get_pacer is not None else None
