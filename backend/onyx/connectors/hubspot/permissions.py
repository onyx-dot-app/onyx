"""Record-level access from HubSpot's permitted-users API. HubSpot does not
expose what a role grants, so this asks which users may view each record and
keeps their emails."""

from collections.abc import Iterable, Iterator

from onyx.access.models import ExternalAccess
from onyx.connectors.hubspot.config import HubSpotObjectType
from onyx.connectors.hubspot.models import (
    HubSpotUser,
)
from onyx.connectors.hubspot.source_operations import (
    HubSpotSourceOperations,
    iter_pages,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# 10,000 users. HubSpot's largest plans sell seats in the low thousands.
MAX_USERS_PAGES = 100
# Private apps appear as users at this domain.
SERVICE_ACCOUNT_DOMAIN_PREFIX = "appserviceaccount."


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

    def __init__(self, ops: HubSpotSourceOperations, portal_id: str) -> None:
        self._ops = ops
        self._portal_id = portal_id
        # User id to email, None when no person owns the id. Filled once per
        # walk, so each unlisted viewer costs one lookup.
        self._emails: dict[int, str | None] | None = None

    def list_users(self) -> Iterator[HubSpotUser]:
        return iter_pages(
            lambda after: self._ops.list_users(after=after), MAX_USERS_PAGES
        )

    def _email_for(self, user_id: int) -> str | None:
        if self._emails is None:
            self._emails = {
                user.id: _clean_email(user.email) for user in self.list_users()
            }
        if user_id in self._emails:
            return self._emails[user_id]
        # The listing leaves out ids HubSpot still names as viewers (deleted
        # users, the app itself), so those resolve one at a time.
        user = self._ops.get_user(user_id=user_id)
        email = _clean_email(user.email) if user else None
        self._emails[user_id] = email
        return email

    def viewers(
        self, object_type: HubSpotObjectType, record_ids: list[str]
    ) -> dict[str, set[int]]:
        """Viewer ids per record. A record HubSpot gives no answer for has none."""
        return self._ops.get_record_viewers(
            portal_id=self._portal_id, object_type=object_type, record_ids=record_ids
        )

    def access_for(self, viewer_ids: Iterable[int]) -> ExternalAccess:
        """Viewers with no person behind them (deleted users, the app itself) are left out."""
        emails: set[str] = set()
        unmatched = 0
        for viewer_id in viewer_ids:
            email = self._email_for(viewer_id)
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
