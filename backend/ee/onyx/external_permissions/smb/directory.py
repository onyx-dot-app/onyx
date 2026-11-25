"""The domain's users and group members from Active Directory, each read once
per sync. Principals are SIDs in upper case."""

from ee.onyx.external_permissions.microsoft_utils.principal_sets import (
    PrincipalDirectory,
)
from onyx.connectors.smb.models import (
    DirectoryGroup,
    DirectoryInfo,
    DirectoryUser,
    EmailAttribute,
)
from onyx.connectors.smb.sid import normalize_sid
from onyx.connectors.smb.source_operations import SmbSourceOperations
from onyx.utils.logger import setup_logger

logger = setup_logger()

_EVERYONE_GROUP_PREFIX = "ad_domain_everyone"
# A user listing still paging past this is a cursor that does not advance.
_MAX_USER_PAGES = 100_000


def user_email(user: DirectoryUser, attribute: EmailAttribute) -> str | None:
    """The address Onyx knows the user by. None for a disabled account, which
    cannot sign in to read anything, and for a user without the attribute."""
    if not user.enabled:
        return None
    address: str | None = (
        user.user_principal_name
        if attribute is EmailAttribute.USER_PRINCIPAL_NAME
        else user.mail or user.user_principal_name
    )
    return address.strip().lower() if address and address.strip() else None


class ActiveDirectory(PrincipalDirectory):
    def __init__(
        self, ops: SmbSourceOperations, email_attribute: EmailAttribute
    ) -> None:
        self._ops = ops
        self._email_attribute = email_attribute
        self._info: DirectoryInfo | None = None
        self._users: dict[str, DirectoryUser] | None = None
        self._groups: dict[str, DirectoryGroup | None] = {}
        self._members: dict[str, frozenset[str]] = {}

    def info(self) -> DirectoryInfo:
        if self._info is None:
            self._info = self._ops.get_directory_info()
        return self._info

    def domain_sid(self) -> str:
        return normalize_sid(self.info().domain_sid)

    def everyone_group_id(self) -> str:
        """The synced group of every user of the domain. It stands for
        Everyone, Authenticated Users and Domain Users. Scoped to the domain,
        since connectors of other domains have their own."""
        return f"{_EVERYONE_GROUP_PREFIX}:{self.domain_sid()}"

    def _all(self) -> dict[str, DirectoryUser]:
        if self._users is None:
            users: dict[str, DirectoryUser] = {}
            cookie: bytes | None = None
            for _ in range(_MAX_USER_PAGES):
                page = self._ops.list_directory_users(
                    base_dn=self.info().base_dn, cookie=cookie
                )
                users.update({normalize_sid(user.sid): user for user in page.users})
                cookie = page.cookie
                if cookie is None:
                    break
            else:
                raise RuntimeError(
                    f"The domain's user listing passed {_MAX_USER_PAGES} pages"
                )
            self._users = users
        return self._users

    def is_user(self, sid: str) -> bool:
        """True also for a disabled user or one with no address: the SID is
        known, and it resolves to nobody."""
        return normalize_sid(sid) in self._all()

    def all_users(self) -> frozenset[str]:
        return frozenset(
            sid for sid, user in self._all().items() if self._email(user) is not None
        )

    def _email(self, user: DirectoryUser) -> str | None:
        return user_email(user, self._email_attribute)

    def user_email(self, user_id: str) -> str | None:
        user: DirectoryUser | None = self._all().get(normalize_sid(user_id))
        return self._email(user) if user is not None else None

    def group(self, sid: str) -> DirectoryGroup | None:
        """The domain group with this SID. None for a SID the domain does not
        know as a group: a local group of the file server, a group of another
        domain, or a deleted group."""
        key: str = normalize_sid(sid)
        if key not in self._groups:
            self._groups[key] = self._ops.find_directory_group(
                base_dn=self.info().base_dn, sid=key
            )
        return self._groups[key]

    def group_members(self, group_id: str) -> frozenset[str]:
        key: str = normalize_sid(group_id)
        if key in self._members:
            return self._members[key]
        group: DirectoryGroup | None = self.group(key)
        if group is None:
            # An access list can still name a deleted group, which holds nobody.
            logger.info("Active Directory has no group %s", key)
            members: frozenset[str] = frozenset()
        else:
            members = frozenset(
                normalize_sid(sid)
                for sid in self._ops.list_group_member_sids(
                    base_dn=self.info().base_dn, group=group
                )
            )
        self._members[key] = members
        return members
