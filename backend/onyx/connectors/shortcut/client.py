import json
import time
from collections.abc import Generator
from typing import Any
import requests

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.shortcut.models import (
    ShortcutComment,
    ShortcutEpic,
    ShortcutStory,
)
from onyx.utils.retry_after import parse_retry_after_seconds

_DEFAULT_SHORTCUT_API_URL = "https://api.app.shortcut.com/api/v3"
_MAX_RETRY_AFTER_SLEEP_SECONDS = 60


class ShortcutClient:
    """Handles communication with the Shortcut API v3."""

    def __init__(
        self,
        api_token: str,
        base_url: str = _DEFAULT_SHORTCUT_API_URL,
    ) -> None:
        self.api_token = api_token.strip()
        self.base_url = base_url.rstrip("/")

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Shortcut-Token": self.api_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OnyxShortcutConnector/1.0",
        }

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code == 429:
            retry_after = parse_retry_after_seconds(response.headers.get("Retry-After"))
            sleep_sec = retry_after if retry_after and retry_after > 0 else 5
            time.sleep(min(sleep_sec, _MAX_RETRY_AFTER_SLEEP_SECONDS))
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        if response.status_code == 401:
            raise CredentialExpiredError(
                "Shortcut API token is invalid or expired (HTTP 401)."
            )
        elif response.status_code == 403:
            raise InsufficientPermissionsError(
                "Shortcut API token does not have permission for this resource (HTTP 403)."
            )
        elif response.status_code == 404:
            raise ConnectorValidationError(
                f"Shortcut resource not found at {url} (HTTP 404)."
            )

        response.raise_for_status()
        return response.json()

    def validate_credentials(self) -> None:
        """Verifies authentication with Shortcut."""
        self._request("/member")

    def get_epics(self) -> list[ShortcutEpic]:
        """Fetches all epics in the workspace."""
        data = self._request("/epics")
        epics: list[ShortcutEpic] = []
        for item in data:
            epics.append(
                ShortcutEpic(
                    id=item.get("id"),
                    name=item.get("name", "Untitled Epic"),
                    description=item.get("description"),
                    state=item.get("state"),
                    app_url=item.get("app_url"),
                    created_at=item.get("created_at"),
                    updated_at=item.get("updated_at"),
                )
            )
        return epics

    def paginate_stories(
        self,
        project_ids: list[int] | None = None,
        epic_ids: list[int] | None = None,
        start_epoch: int | None = None,
        batch_size: int = 50,
    ) -> Generator[ShortcutStory, None, None]:
        """Paginates through stories in the workspace matching project/epic filters."""
        next_cursor: str | None = None

        while True:
            params: dict[str, Any] = {"page_size": batch_size}
            if next_cursor:
                params["next"] = next_cursor

            query_parts: list[str] = []
            if project_ids:
                proj_q = " ".join(f"project:{pid}" for pid in project_ids)
                query_parts.append(f"({proj_q})")
            if epic_ids:
                epic_q = " ".join(f"epic:{eid}" for eid in epic_ids)
                query_parts.append(f"({epic_q})")

            if query_parts:
                params["query"] = " ".join(query_parts)

            data = self._request("/stories/search", params=params)
            data_items = data.get("data", [])
            if not data_items:
                break

            for item in data_items:
                # Check timestamps for polling window
                updated_at = item.get("updated_at")
                created_at = item.get("created_at")

                comments: list[ShortcutComment] = []
                for c in item.get("comments", []):
                    comments.append(
                        ShortcutComment(
                            id=c.get("id"),
                            text=c.get("text", ""),
                            author_id=c.get("author_id"),
                            created_at=c.get("created_at"),
                            updated_at=c.get("updated_at"),
                        )
                    )

                labels = [label.get("name", "") for label in item.get("labels", []) if label.get("name")]

                story = ShortcutStory(
                    id=item.get("id"),
                    name=item.get("name", "Untitled Story"),
                    description=item.get("description"),
                    story_type=item.get("story_type", "feature"),
                    workflow_state_id=item.get("workflow_state_id"),
                    epic_id=item.get("epic_id"),
                    project_id=item.get("project_id"),
                    app_url=item.get("app_url"),
                    created_at=created_at,
                    updated_at=updated_at,
                    comments=comments,
                    labels=labels,
                    completed=bool(item.get("completed", False)),
                    raw_data=item,
                )
                yield story

            next_cursor = data.get("next")
            if not next_cursor:
                break
