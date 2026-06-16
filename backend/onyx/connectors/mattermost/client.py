"""Thin Mattermost REST API (v4) client.

A single ``requests.Session`` with bearer auth, cursor-based pagination helpers,
and retry/backoff that honors Mattermost's 429 rate-limit headers. Kept dependency
free (``requests`` only) and intentionally small, mirroring how the Slack connector
wraps its own web client.
"""
import time
from typing import Any

import requests

from onyx.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_TIMEOUT = 30
DEFAULT_PER_PAGE = 200


class MattermostClientError(Exception):
    """Raised for non-retryable Mattermost API errors."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Mattermost API error {status_code}: {message}")


class MattermostClient:
    def __init__(
        self,
        base_url: str,
        access_token: str,
        max_retries: int = 5,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api = f"{self.base_url}/api/v4"
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {access_token}"})

    # ---- low-level ----
    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.api}{path}"
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.request(
                    method, url, timeout=self.timeout, **kwargs
                )
            except requests.RequestException as e:
                last_exc = e
                time.sleep(min(2**attempt, 30))
                continue

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                reset = resp.headers.get("X-Ratelimit-Reset")
                if retry_after is not None:
                    wait = float(retry_after)
                elif reset is not None:
                    wait = max(0.0, float(reset) - time.time())
                else:
                    wait = float(2**attempt)
                logger.warning("Mattermost rate limited; backing off %.1fs", wait)
                time.sleep(min(wait, 60))
                continue

            if 500 <= resp.status_code < 600:
                logger.warning(
                    "Mattermost %s on %s; retrying", resp.status_code, path
                )
                time.sleep(min(2**attempt, 30))
                continue

            if resp.status_code >= 400:
                raise MattermostClientError(resp.status_code, resp.text[:500])
            return resp

        if last_exc is not None:
            raise last_exc
        raise MattermostClientError(0, f"exhausted retries for {path}")

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params).json()

    # ---- typed helpers ----
    def get_me(self) -> dict:
        return self.get("/users/me")

    def get_my_teams(self) -> list[dict]:
        return self.get("/users/me/teams")

    def get_channels_for_team(self, user_id: str, team_id: str) -> list[dict]:
        """Channels the user/bot is a member of on a team (includes private)."""
        return self.get(f"/users/{user_id}/teams/{team_id}/channels")

    def get_channel_posts(
        self, channel_id: str, before: str | None = None, per_page: int = DEFAULT_PER_PAGE
    ) -> dict:
        """One page of a channel's posts, newest-first.

        Page backward with the ``before`` post-id cursor; the response's
        ``prev_post_id`` is the cursor for the next (older) page.
        """
        params: dict[str, Any] = {"per_page": per_page}
        if before:
            params["before"] = before
        return self.get(f"/channels/{channel_id}/posts", params=params)

    def get_thread(self, root_id: str) -> dict:
        """All posts in the thread rooted at ``root_id`` (a PostList)."""
        return self.get(f"/posts/{root_id}/thread")

    def get_user(self, user_id: str) -> dict:
        return self.get(f"/users/{user_id}")
