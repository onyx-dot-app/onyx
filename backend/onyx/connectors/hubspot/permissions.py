"""Record-level access from HubSpot's permitted-users API. HubSpot does not
expose what a role grants, so this asks which users may view each record and
keeps their emails."""

from collections.abc import Iterable, Iterator
from typing import TypeVar

import requests
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.hubspot.config import HUBSPOT_OBJECT_SPECS, HubSpotObjectType
from onyx.connectors.hubspot.models import (
    ApiActionPermittedUsers,
    ApiPermittedUsersResponse,
    ApiUsersResponse,
    HubSpotUser,
)
from onyx.connectors.hubspot.rate_limit import HubSpotRateLimiter
from onyx.utils.logger import setup_logger

logger = setup_logger()

HUBSPOT_API_BASE = "https://api.hubapi.com"
USERS_PATH = "/settings/users/2026-09"
PERMITTED_USERS_PATH = "/resource-permissions/v3/permitted-users"
VIEW_ACTION = "crm-object:VIEW"
# Measured: HubSpot rejects a request naming more resources than this.
PERMITTED_USERS_BATCH_SIZE = 20
USERS_PAGE_SIZE = 100
# 10,000 users. HubSpot's largest plans sell seats in the low thousands.
MAX_USERS_PAGES = 100
# Private apps appear as users at this domain.
SERVICE_ACCOUNT_DOMAIN_PREFIX = "appserviceaccount."

_M = TypeVar("_M", bound=BaseModel)

QueryParams = dict[str, str | int | list[str]]


class HubSpotApiError(Exception):
    """A 4xx or 5xx answer. Carries the status and headers the rate limiter reads."""

    def __init__(self, path: str, response: requests.Response) -> None:
        self.path = path
        self.status = response.status_code
        self.headers = response.headers
        super().__init__(
            f"HubSpot returned {self.status} for GET {path}: {response.text[:200]}"
        )


def _clean_email(email: str | None) -> str | None:
    """A private app's own HubSpot-issued address is not a person, so it is dropped."""
    if not email:
        return None
    cleaned = email.strip().lower()
    if cleaned.split("@")[-1].startswith(SERVICE_ACCOUNT_DOMAIN_PREFIX):
        return None
    return cleaned or None


class HubSpotPermissionReader:
    """Turns record ids into the emails of the users HubSpot lets view them."""

    def __init__(
        self, access_token: str, portal_id: str, rate_limiter: HubSpotRateLimiter
    ) -> None:
        self._headers: dict[str, str] = {"Authorization": f"Bearer {access_token}"}
        self._portal_id: str = portal_id
        self._rate_limiter: HubSpotRateLimiter = rate_limiter
        # User id to email, None when no person owns the id. Filled once per
        # walk, so each unlisted viewer costs one lookup.
        self._emails: dict[int, str | None] | None = None

    def _get(self, model: type[_M], path: str, params: QueryParams) -> _M:
        def request() -> _M:
            # Raised inside the limited call so a 429 is retried with its headers.
            response: requests.Response = requests.get(
                f"{HUBSPOT_API_BASE}{path}",
                headers=self._headers,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                raise HubSpotApiError(path, response)
            return model.model_validate(response.json())

        return self._rate_limiter.call(request)

    def probe_users(self) -> None:
        self._get(ApiUsersResponse, USERS_PATH, {"limit": 1})

    def list_users(self) -> Iterator[HubSpotUser]:
        params: QueryParams = {"limit": USERS_PAGE_SIZE}
        for _ in range(MAX_USERS_PAGES):
            page: ApiUsersResponse = self._get(ApiUsersResponse, USERS_PATH, params)
            yield from page.results
            after: str | None = (
                page.paging.next.after if page.paging and page.paging.next else None
            )
            if not after:
                return
            params["after"] = after
        raise RuntimeError(f"HubSpot user listing ran past {MAX_USERS_PAGES} pages")

    def _email_for(self, user_id: int) -> str | None:
        if self._emails is None:
            self._emails = {
                user.id: _clean_email(user.email) for user in self.list_users()
            }
        if user_id in self._emails:
            return self._emails[user_id]
        # The listing leaves out ids HubSpot still names as viewers (deleted
        # users, the app itself), so those resolve one at a time.
        try:
            email: str | None = _clean_email(
                self._get(HubSpotUser, f"{USERS_PATH}/{user_id}", {}).email
            )
        except HubSpotApiError as e:
            if e.status != 404:
                raise
            email = None
        self._emails[user_id] = email
        return email

    def viewers(
        self, object_type: HubSpotObjectType, record_ids: list[str]
    ) -> dict[str, set[int]]:
        """Viewer ids per record. A record HubSpot gives no answer for has none."""
        if len(record_ids) > PERMITTED_USERS_BATCH_SIZE:
            raise ValueError(
                f"HubSpot answers for at most {PERMITTED_USERS_BATCH_SIZE} records per call"
            )
        type_id: str = HUBSPOT_OBJECT_SPECS[object_type].type_id
        hcrns: dict[str, str] = {
            f"hcrn:{self._portal_id}:crm-object:{type_id}:{record_id}": record_id
            for record_id in record_ids
        }
        response: ApiPermittedUsersResponse = self._get(
            ApiPermittedUsersResponse, PERMITTED_USERS_PATH, {"resource": list(hcrns)}
        )
        viewers: dict[str, set[int]] = {}
        for hcrn, record_id in hcrns.items():
            actions: dict[str, ApiActionPermittedUsers] | None = response.resources.get(
                hcrn
            )
            if actions is None:
                logger.warning(
                    "HubSpot gave no viewer list for %s %s, so it stays private",
                    object_type,
                    record_id,
                )
                viewers[record_id] = set()
                continue
            view: ApiActionPermittedUsers | None = actions.get(VIEW_ACTION)
            viewers[record_id] = set(view.permitted_users) if view else set()
        return viewers

    def access_for(self, viewer_ids: Iterable[int]) -> ExternalAccess:
        """Viewers with no person behind them (deleted users, the app itself) are left out."""
        emails: set[str] = set()
        unmatched: int = 0
        for viewer_id in viewer_ids:
            email: str | None = self._email_for(viewer_id)
            if email is None:
                unmatched += 1
                continue
            emails.add(email)
        if unmatched:
            logger.debug("%s HubSpot viewers have no user email", unmatched)
        return ExternalAccess(
            external_user_emails=emails,
            external_user_group_ids=set(),
            is_public=False,
        )
