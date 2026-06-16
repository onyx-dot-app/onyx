"""Template for proactive, single-flighted OAuth token refresh.

Both Craft external apps and MCP servers refresh the same way: a cheap staleness
pre-check, then — under a Redis single-flight lock — re-read, exchange the refresh
token, and persist, with a fixed terminal/transient/contention/infra policy. That
fixed skeleton lives here (Template Method); each subsystem subclasses it and fills
in only what genuinely differs (its token store, lock key, dead-grant policy, and
success return).
"""

from abc import ABC
from abc import abstractmethod
from typing import ClassVar
from typing import Generic
from typing import TypeVar

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from onyx.oauth.errors import TokenRefreshTerminalError
from onyx.oauth.errors import TokenRefreshTransientError
from onyx.redis.lock_context import redis_shared_lock
from onyx.redis.lock_context import RedisSharedLockAcquisitionError
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The successful-refresh return type: `None` for callers that re-read the store
# afterwards (the external-apps egress gate), or e.g. the fresh auth headers for
# callers that apply the result directly (an MCP tool call).
R = TypeVar("R")


class SingleFlightTokenRefresher(ABC, Generic[R]):
    """Refresh an OAuth access token if it's expired/expiring, single-flighted.

    The fixed algorithm in :meth:`run` — stale pre-check, Redis-locked
    re-read/exchange/persist, and terminal/transient/contention/infra routing —
    is shared. Subclasses own everything that varies: :meth:`lock_name`,
    :meth:`is_stale`, :meth:`refresh_under_lock`, and :meth:`on_terminal`.

    :meth:`run` never raises for a refresh *outcome*: a dead grant runs the
    subclass's terminal policy; a transient, lock-contention, or infra failure
    keeps the existing token in place so the caller proceeds with it.
    """

    # Held long enough for the refresh POST + DB write; short wait so a contended
    # caller doesn't pin a worker thread (a timed-out waiter proceeds with the
    # current token rather than blocking on the winner).
    lock_held_s: ClassVar[float] = 30.0
    lock_wait_s: ClassVar[float] = 5.0

    # Prefix for this refresher's structured log lines (e.g. "ea_token_refresh").
    log_prefix: ClassVar[str] = "oauth_token_refresh"

    @abstractmethod
    def lock_name(self) -> str:
        """The single-flight key — unique per refreshable credential."""

    @abstractmethod
    def is_stale(self) -> bool:
        """Whether the stored token is expired/expiring and refreshable. A cheap
        check that takes its own short session; run once before taking the lock so
        a fresh token is a fast no-op."""

    @abstractmethod
    def refresh_under_lock(self) -> R | None:
        """Holding the lock: re-read (double-checking against a concurrent winner),
        exchange the refresh token, and persist. Returns the success value, or
        ``None`` when there's nothing to do (winner already refreshed, inputs
        missing, …). Raises :class:`TokenRefreshTerminalError` /
        :class:`TokenRefreshTransientError` on a failed grant."""

    @abstractmethod
    def on_terminal(self, error: TokenRefreshTerminalError) -> R | None:
        """Apply the dead-grant policy (clear the credential / flag a reconnect).
        The refresh token can't be salvaged; retrying won't help."""

    def on_transient(self, error: TokenRefreshTransientError) -> R | None:
        """A retryable failure (network / 5xx / non-JSON): keep the existing token
        and retry on a later request. Override only to surface it differently."""
        logger.warning("%s.transient error=%s", self.log_prefix, error)
        return None

    def run(self) -> R | None:
        try:
            if not self.is_stale():
                return None
            with redis_shared_lock(
                self.lock_name(),
                max_time_lock_held_s=self.lock_held_s,
                wait_for_lock_s=self.lock_wait_s,
                logger=logger,
            ):
                try:
                    return self.refresh_under_lock()
                except TokenRefreshTerminalError as exc:
                    return self.on_terminal(exc)
                except TokenRefreshTransientError as exc:
                    return self.on_transient(exc)
        except RedisSharedLockAcquisitionError:
            # Another worker holds the lock and is refreshing; proceed with the
            # current token rather than waiting it out.
            logger.info("%s.lock_contended lock=%s", self.log_prefix, self.lock_name())
            return None
        except (RedisError, SQLAlchemyError) as exc:
            # Transient infra failure (Redis down / DB blip): keep the existing
            # token and let the request through, never raise.
            logger.warning("%s.infra_unavailable error=%s", self.log_prefix, exc)
            return None
