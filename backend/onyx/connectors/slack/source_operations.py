"""Slack source-operations gateway: every Slack API call lives here.

This is the single file in ``onyx/connectors/slack/`` and
``ee/onyx/external_permissions/slack/`` allowed to import ``slack_sdk`` (the
import-fence test enforces it). It owns client construction -- one
redis-coordinated path shared by indexing, perm-sync, and capability checks --
and exposes each Slack API method as a stamped operation returning plain data.

Transport internals (``OnyxSlackWebClient``, ``OnyxRedisSlackRetryHandler``)
were absorbed from their former sibling modules: they subclass slack_sdk types,
so the fence requires them to live here.
"""

import random
import threading
import time
from collections.abc import Callable, Generator
from enum import Enum
from http.client import IncompleteRead, RemoteDisconnected
from typing import Any, Dict, Optional, cast
from urllib.error import URLError
from urllib.request import Request

from redis.lock import Lock as RedisLock
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError as SlackApiError  # Re-export, see below.
from slack_sdk.http_retry import ConnectionErrorRetryHandler, RetryHandler
from slack_sdk.http_retry.builtin_interval_calculators import (
    FixedValueRetryIntervalCalculator,
)
from slack_sdk.http_retry.handler import RetryHandler as BaseRetryHandler
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.state import RetryState
from slack_sdk.web import SlackResponse

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds

# ``SlackApiError`` is re-exported as part of the operation contract: callers
# branch on Slack error slugs (``is_archived``, ``missing_scope``, ...) and the
# type carries response data, not a live client, so it does not undermine the
# gateway boundary. Import it from here, never from ``slack_sdk``.

logger = setup_logger()

# Messages / items requested per page for paginated Slack calls.
_SLACK_LIMIT = 900

# Used to serialize access to the retry TTL.
ONYX_SLACK_LOCK_TTL = 1800  # How long the lock is allowed to idle before it expires.
ONYX_SLACK_LOCK_BLOCKING_TIMEOUT = 60  # How long to wait for the lock per attempt.
ONYX_SLACK_LOCK_TOTAL_BLOCKING_TIMEOUT = 3600  # How long to wait for the lock total.

_MAX_RETRIES = 7  # Arbitrarily selected.

# Timeout for the uncoordinated client behind ``fast=True`` operations.
_FAST_TIMEOUT = 1

_TEMPORARILY_UNTESTED = "Not yet tested: checks land in the Slack capability checks PR."


class SlackChannelVariant(str, Enum):
    """Permission class of a channel-scoped operation call.

    Reading private channels needs the ``groups:*`` scope family where public
    channels need ``channels:*``; the variant classifies each call so coverage
    is counted per permission class.
    """

    PUBLIC = "public"
    PRIVATE = "private"


class OnyxRedisSlackRetryHandler(BaseRetryHandler):
    """This class uses Redis to share a rate limit among multiple threads.

    As currently implemented, this code is already surrounded by a lock in Redis
    via an override of _perform_urllib_http_request in OnyxSlackWebClient.

    This just sets the desired retry delay with TTL in redis. In conjunction
    with a custom subclass of the client, the value is read and obeyed prior to
    an API call and also serialized.

    Another way to do this is just to do exponential backoff. Might be easier?

    Adapted from slack's RateLimitErrorRetryHandler.
    """

    """RetryHandler that does retries for rate limited errors."""

    def __init__(
        self,
        max_retry_count: int,
        delay_key: str,
        r: TenantRedisClient,
    ):
        """
        delay_lock: the redis key to use with RedisLock (to synchronize access
        to delay_key)
        delay_key: the redis key containing a shared TTL
        """
        super().__init__(max_retry_count=max_retry_count)
        self._redis: TenantRedisClient = r
        self._delay_key = delay_key

    def _can_retry(
        self,
        *,
        state: RetryState,  # noqa: ARG002
        request: HttpRequest,  # noqa: ARG002
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,  # noqa: ARG002
    ) -> bool:
        return response is not None and response.status_code == 429

    def prepare_for_next_attempt(
        self,
        *,
        state: RetryState,
        request: HttpRequest,  # noqa: ARG002
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> None:
        """
        As initially designed by the SDK authors, this function is responsible
        for the wait to retry ... aka we actually sleep in this function.

        This doesn't work well with multiple clients because every thread is
        unaware of the current retry value until it actually calls the endpoint.

        We're combining this with an actual subclass of the slack web client so
        that the delay is used BEFORE calling an API endpoint. The subclassed
        client has already taken the lock in redis when this method is called.
        """
        ttl_ms: int | None = None

        retry_after_value: str | None = None
        retry_after_header_name: Optional[str] = None
        duration_s: float = 1.0  # seconds

        if response is None:
            # NOTE(rkuo): this logic comes from RateLimitErrorRetryHandler.
            # This reads oddly, as if the caller itself could raise the
            # exception. We don't have the luxury of changing this.
            if error:
                raise error

            return

        state.next_attempt_requested = True  # this signals the caller to retry

        # Calculate wait duration based on retry-after + some jitter.
        for k in response.headers.keys():
            if k.lower() == "retry-after":
                retry_after_header_name = k
                break

        try:
            if retry_after_header_name is None:
                # This situation usually does not arise. Just in case.
                raise ValueError(
                    "OnyxRedisSlackRetryHandler.prepare_for_next_attempt: retry-after header name is None"
                )

            retry_after_header_value = response.headers.get(retry_after_header_name)
            if not retry_after_header_value:
                raise ValueError(
                    "OnyxRedisSlackRetryHandler.prepare_for_next_attempt: retry-after header value is None"
                )

            # Handle case where header value might be a list.
            retry_after_value = (
                retry_after_header_value[0]
                if isinstance(retry_after_header_value, list)
                else retry_after_header_value
            )

            parsed_retry_after = parse_retry_after_seconds(retry_after_value)
            if parsed_retry_after is None:
                raise ValueError(
                    "OnyxRedisSlackRetryHandler.prepare_for_next_attempt: "
                    "could not parse retry-after value"
                )
            jitter = parsed_retry_after * 0.25 * random.random()
            duration_s = parsed_retry_after + jitter
        except ValueError:
            duration_s += random.random()

        # Read and extend the ttl.
        ttl_ms = self._redis.pttl(self._delay_key)
        if ttl_ms < 0:  # negative values are error status codes ... see docs
            ttl_ms = 0
        ttl_ms_new = ttl_ms + int(duration_s * 1000.0)
        self._redis.set(self._delay_key, "1", px=ttl_ms_new)

        logger.warning(
            "OnyxRedisSlackRetryHandler.prepare_for_next_attempt setting delay: current_attempt=%s retry-after=%s ttl_ms_new=%r",
            state.current_attempt,
            retry_after_value,
            ttl_ms_new,
        )

        state.increment_current_attempt()


class OnyxSlackWebClient(WebClient):
    """Use in combination with the Onyx Retry Handler.

    This client wrapper enforces a proper retry delay through redis BEFORE the
    api call so that multiple clients can synchronize and rate limit properly.

    The retry handler writes the correct delay value to redis so that it is can
    be used by this wrapper.
    """

    def __init__(
        self,
        delay_lock: str,
        delay_key: str,
        r: TenantRedisClient,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._delay_key = delay_key
        self._delay_lock = delay_lock
        self._redis: TenantRedisClient = r
        self.num_requests: int = 0
        self._lock = threading.Lock()

    def _perform_urllib_http_request(
        self, *, url: str, args: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        By locking around the base class method, we ensure that both the delay
        from Redis and parsing/writing of retry values to Redis are handled
        properly in one place.
        """
        # Lock and extend the ttl.
        lock: RedisLock = self._redis.lock(
            self._delay_lock,
            timeout=ONYX_SLACK_LOCK_TTL,
        )

        # Try to acquire the lock.
        start = time.monotonic()
        while True:
            acquired = lock.acquire(blocking_timeout=ONYX_SLACK_LOCK_BLOCKING_TIMEOUT)
            if acquired:
                break

            # If we couldn't acquire the lock but it exists, there's at least
            # some activity so keep trying...
            if self._redis.exists(self._delay_lock):
                continue

            if time.monotonic() - start > ONYX_SLACK_LOCK_TOTAL_BLOCKING_TIMEOUT:
                raise RuntimeError(
                    f"OnyxSlackWebClient._perform_urllib_http_request - "
                    f"timed out waiting for lock: {ONYX_SLACK_LOCK_TOTAL_BLOCKING_TIMEOUT=}"
                )

        try:
            result = super()._perform_urllib_http_request(url=url, args=args)
        finally:
            if lock.owned():
                lock.release()
            else:
                logger.warning(
                    "OnyxSlackWebClient._perform_urllib_http_request lock not owned on release"
                )

        return result

    def _perform_urllib_http_request_internal(
        self,
        url: str,
        req: Request,
    ) -> Dict[str, Any]:
        """
        Overrides the internal method which is mostly the direct call to
        urllib/urlopen ... so this is a good place to perform our delay.
        """

        # Read and execute the delay.
        delay_ms = self._redis.pttl(self._delay_key)
        if delay_ms < 0:  # Negative values are error status codes ... see docs.
            delay_ms = 0

        if delay_ms > 0:
            logger.warning(
                "OnyxSlackWebClient._perform_urllib_http_request_internal delay: delay_ms=%r self.num_requests=%r",
                delay_ms,
                self.num_requests,
            )

            time.sleep(delay_ms / 1000.0)

        result = super()._perform_urllib_http_request_internal(url, req)

        with self._lock:
            self.num_requests += 1

        # The delay key should have naturally expired by this point.
        return result


def make_credential_prefix(key: str) -> str:
    return f"connector:slack:credential_{key}"


def make_delay_lock(prefix: str) -> str:
    return f"{prefix}:delay_lock"


def make_delay_key(prefix: str) -> str:
    return f"{prefix}:delay"


def _connection_error_retry_handler(
    max_retry_count: int,
) -> ConnectionErrorRetryHandler:
    return ConnectionErrorRetryHandler(
        max_retry_count=max_retry_count,
        interval_calculator=FixedValueRetryIntervalCalculator(),
        error_types=[
            URLError,
            ConnectionResetError,
            RemoteDisconnected,
            IncompleteRead,
        ],
    )


def make_slack_web_client(
    prefix: str, token: str, max_retry_count: int, r: TenantRedisClient
) -> WebClient:
    """Builds the redis-coordinated client shared by all Slack consumers."""
    delay_lock = make_delay_lock(prefix)
    delay_key = make_delay_key(prefix)

    # NOTE: Slack has a built in RateLimitErrorRetryHandler, but it isn't
    # designed for concurrent workers. We've extended it with
    # OnyxRedisSlackRetryHandler.
    onyx_rate_limit_error_retry_handler = OnyxRedisSlackRetryHandler(
        max_retry_count=max_retry_count,
        delay_key=delay_key,
        r=r,
    )
    custom_retry_handlers: list[RetryHandler] = [
        _connection_error_retry_handler(max_retry_count),
        onyx_rate_limit_error_retry_handler,
    ]

    client = OnyxSlackWebClient(
        delay_lock=delay_lock,
        delay_key=delay_key,
        r=r,
        token=token,
        retry_handlers=custom_retry_handlers,
    )
    return client


def _paginate(
    call: Callable[..., SlackResponse],
    limit: int | None = None,
    **kwargs: Any,
) -> Generator[dict[str, Any], None, None]:
    """Handles cursor pagination; yields each validated page as a plain dict.

    Single-page callers take ``next(...)`` and read
    ``response_metadata.next_cursor`` themselves -- pages are lazy, so no second
    request fires.
    """
    cursor: str | None = None
    has_more = True
    while has_more:
        response = call(
            cursor=cursor,
            limit=limit if limit is not None else _SLACK_LIMIT,
            **kwargs,
        )
        response.validate()
        yield cast(dict[str, Any], response.data)
        cursor = cast(dict[str, Any], response.get("response_metadata", {})).get(
            "next_cursor", ""
        )
        has_more = bool(cursor)


def _response_data(response: SlackResponse) -> dict[str, Any]:
    """Extracts the plain payload; operations never return live SDK objects."""
    return cast(dict[str, Any], response.data)


class SlackSourceOperations(SourceOperations):
    """All Slack remote interactions, one method per Slack API method.

    Two clients, both owned here:
    - The coordinated client (default): redis-synchronized rate limiting shared
      across every worker touching this credential, plus connection-error and
      rate-limit retry handlers. ``connector_specific_config["use_redis"] is
      False`` downgrades it to a bare client with the connection-error handler
      only (dev/test escape hatch, mirrors the old connector flag).
    - The fast client (``fast=True`` operations): bare, ``timeout=1``, no
      retries. For synchronous user-facing paths (settings validation) where the
      coordinated client may block behind a rate-limited indexing job's backoff
      for up to an hour.

    Both are built lazily on first use: construction reads the credential (via
    the provider, which audits the decrypt), and credential-time report runs
    must not decrypt for gateways whose operations never run.
    """

    source = DocumentSource.SLACK
    sdk_modules = ("slack_sdk",)

    _cached_client: WebClient | None = None
    _cached_fast_client: WebClient | None = None
    # Client construction is idempotent (both builds coordinate through redis),
    # so a shared class-level lock is only hygiene against duplicate builds.
    _client_build_lock: threading.Lock = threading.Lock()

    def _bot_token(self) -> str:
        return cast(str, self.credentials_provider.get_credentials()["slack_bot_token"])

    def _client(self) -> WebClient:
        if self._cached_client is None:
            with self._client_build_lock:
                if self._cached_client is None:
                    self._cached_client = self._build_client()
        return self._cached_client

    def _fast_client(self) -> WebClient:
        if self._cached_fast_client is None:
            with self._client_build_lock:
                if self._cached_fast_client is None:
                    self._cached_fast_client = WebClient(
                        token=self._bot_token(), timeout=_FAST_TIMEOUT
                    )
        return self._cached_fast_client

    def _build_client(self) -> WebClient:
        config = self.connector_specific_config or {}
        use_redis = bool(config.get("use_redis", True))
        token = self._bot_token()
        if not use_redis:
            return WebClient(
                token=token,
                retry_handlers=[_connection_error_retry_handler(_MAX_RETRIES)],
            )
        tenant_id = self.credentials_provider.get_tenant_id()
        if not tenant_id:
            raise ValueError("tenant_id cannot be None!")
        prefix = make_credential_prefix(self.credentials_provider.get_provider_key())
        return make_slack_web_client(
            prefix, token, _MAX_RETRIES, get_redis_client(tenant_id=tenant_id)
        )

    def _client_for(self, fast: bool) -> WebClient:
        return self._fast_client() if fast else self._client()

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_TEMPORARILY_UNTESTED,
    )
    def check_auth(self, *, fast: bool = False) -> dict[str, Any]:
        """``auth.test``: token validity, workspace url, Grid enterprise id."""
        return _response_data(self._client_for(fast).auth_test())

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        variants=(SlackChannelVariant.PUBLIC, SlackChannelVariant.PRIVATE),
        untested=_TEMPORARILY_UNTESTED,
    )
    def list_channels(
        self,
        *,
        variant: SlackChannelVariant,
        channel_types: list[str],
        exclude_archived: bool | None = None,
        team_id: str | None = None,
        limit: int | None = None,
        fast: bool = False,
    ) -> Generator[dict[str, Any], None, None]:
        """``conversations.list``, paginated.

        The variant names the permission class: a call whose ``channel_types``
        include private channels classifies as ``private`` (it fails without
        ``groups:read``), public-only calls as ``public``.
        """
        del variant  # Classification-only; ``channel_types`` carries the request.
        kwargs: dict[str, Any] = {"types": channel_types}
        if exclude_archived is not None:
            kwargs["exclude_archived"] = exclude_archived
        if team_id is not None:
            kwargs["team_id"] = team_id
        return _paginate(
            self._client_for(fast).conversations_list, limit=limit, **kwargs
        )

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_TEMPORARILY_UNTESTED,
    )
    def list_teams(
        self, *, limit: int | None = None, fast: bool = False
    ) -> Generator[dict[str, Any], None, None]:
        """
        ``auth.teams.list``, paginated: Grid org workspaces (``team:read``).
        """
        return _paginate(self._client_for(fast).auth_teams_list, limit=limit)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested="Production degrades gracefully: a failed team.info only costs "
        "the workspace URL on Grid message links.",
    )
    def fetch_team_info(self, *, team_id: str) -> dict[str, Any]:
        """``team.info`` for one Grid workspace."""
        return _response_data(self._client().team_info(team=team_id))

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested="Side effect: joins the bot to the channel; probing it would "
        "mutate workspace state.",
    )
    def join_channel(self, *, channel_id: str) -> dict[str, Any]:
        """``conversations.join``: the bot must be a member to read messages.

        Only works for public channels; private-channel membership requires an
        invite, so joining one raises a ``SlackApiError``.
        """
        return _response_data(self._client().conversations_join(channel=channel_id))

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        variants=(SlackChannelVariant.PUBLIC, SlackChannelVariant.PRIVATE),
        untested=_TEMPORARILY_UNTESTED,
    )
    def fetch_channel_history(
        self,
        *,
        variant: SlackChannelVariant,
        channel_id: str,
        oldest: str | None = None,
        latest: str | None = None,
        limit: int | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """``conversations.history``, paginated.

        The variant is the channel's privacy (``channels:history`` vs
        ``groups:history``), from ``channel["is_private"]`` at the call site.
        """
        del variant  # Classification-only; the channel id carries the request.
        return _paginate(
            self._client().conversations_history,
            limit=limit,
            channel=channel_id,
            oldest=oldest,
            latest=latest,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        variants=(SlackChannelVariant.PUBLIC, SlackChannelVariant.PRIVATE),
        untested=_TEMPORARILY_UNTESTED,
    )
    def fetch_thread_replies(
        self, *, variant: SlackChannelVariant, channel_id: str, thread_ts: str
    ) -> Generator[dict[str, Any], None, None]:
        """``conversations.replies``, paginated. Variant as in history."""
        del variant  # Classification-only; the channel id carries the request.
        return _paginate(
            self._client().conversations_replies, channel=channel_id, ts=thread_ts
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_TEMPORARILY_UNTESTED,
    )
    def fetch_channel_info(self, *, channel_id: str) -> dict[str, Any]:
        """
        ``conversations.info``. No variants: the call exists to discover the
        channel (including its privacy), so it cannot classify itself.
        """
        return _response_data(self._client().conversations_info(channel=channel_id))

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_TEMPORARILY_UNTESTED,
    )
    def fetch_user_info(self, user_id: str) -> dict[str, Any]:
        """
        ``users.info``. Positional ``user_id`` on purpose: the bound method
        doubles as the ``FetchUserInfo`` callable that user-resolving helpers
        (shared with onyxbot) take injected.
        """
        return _response_data(self._client().users_info(user=user_id))

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_TEMPORARILY_UNTESTED,
    )
    def list_users(
        self,
        *,
        team_id: str | None = None,
        limit: int | None = None,
        fast: bool = False,
    ) -> Generator[dict[str, Any], None, None]:
        """
        ``users.list``, paginated; ``team_id`` scopes to one Grid workspace.
        """
        kwargs: dict[str, Any] = {}
        if team_id is not None:
            kwargs["team_id"] = team_id
        return _paginate(self._client_for(fast).users_list, limit=limit, **kwargs)

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_TEMPORARILY_UNTESTED,
    )
    def list_channel_members(
        self, *, channel_id: str
    ) -> Generator[dict[str, Any], None, None]:
        """``conversations.members``, paginated."""
        return _paginate(self._client().conversations_members, channel=channel_id)

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested="Dormant by design: Slack group sync is unused (channel access "
        "resolves usergroups to individual users).",
    )
    def list_usergroups(self) -> Generator[dict[str, Any], None, None]:
        """``usergroups.list``, paginated."""
        return _paginate(self._client().usergroups_list)

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested="Dormant by design: Slack group sync is unused (channel access "
        "resolves usergroups to individual users).",
    )
    def list_usergroup_members(
        self, *, usergroup_id: str
    ) -> Generator[dict[str, Any], None, None]:
        """``usergroups.users.list``, paginated."""
        return _paginate(self._client().usergroups_users_list, usergroup=usergroup_id)
