"""An Active Directory domain in memory, behind the gateway's operations."""

from unittest.mock import MagicMock, create_autospec

from onyx.connectors.smb.models import (
    DirectoryGroup,
    DirectoryGroupPage,
    DirectoryInfo,
    DirectoryUser,
    DirectoryUserPage,
)
from onyx.connectors.smb.source_operations import SmbSourceOperations

DOMAIN_SID = "S-1-5-21-1-2-3"
BASE_DN = "DC=corp,DC=example,DC=com"

ALICE = f"{DOMAIN_SID}-1101"
BOB = f"{DOMAIN_SID}-1102"
CAROL = f"{DOMAIN_SID}-1103"
DISABLED_DAVE = f"{DOMAIN_SID}-1104"
SERVICE = f"{DOMAIN_SID}-1105"
ENGINEERING = f"{DOMAIN_SID}-2001"
RESTRICTED = f"{DOMAIN_SID}-2002"
DOMAIN_USERS = f"{DOMAIN_SID}-513"

USERS: list[DirectoryUser] = [
    DirectoryUser(
        sid=ALICE, mail="Alice@Example.com", user_principal_name="alice@corp"
    ),
    DirectoryUser(sid=BOB, mail="bob@example.com"),
    DirectoryUser(sid=CAROL, mail="carol@example.com"),
    DirectoryUser(sid=DISABLED_DAVE, mail="dave@example.com", enabled=False),
    # No mail: the user principal name is the fallback.
    DirectoryUser(sid=SERVICE, user_principal_name="svc@corp.example.com"),
]
# Members as the directory returns them: nested groups already expanded.
GROUP_MEMBERS: dict[str, list[str]] = {
    ENGINEERING: [ALICE, BOB],
    RESTRICTED: [CAROL, DISABLED_DAVE],
    DOMAIN_USERS: [ALICE, BOB, CAROL, DISABLED_DAVE, SERVICE],
}


def group(sid: str) -> DirectoryGroup:
    return DirectoryGroup(sid=sid, distinguished_name=f"CN={sid},{BASE_DN}", name=sid)


def directory_ops(users: list[DirectoryUser] | None = None) -> MagicMock:
    """A gateway that serves the users in pages of two and the groups in one
    page."""
    served: list[DirectoryUser] = USERS if users is None else users
    ops = create_autospec(SmbSourceOperations, instance=True)
    ops.get_directory_info.return_value = DirectoryInfo(
        base_dn=BASE_DN, domain_sid=DOMAIN_SID
    )

    def list_users(
        *,
        base_dn: str,  # noqa: ARG001
        cookie: bytes | None = None,
        page_size: int = 2,  # noqa: ARG001
    ) -> DirectoryUserPage:
        start: int = int(cookie or b"0")
        end: int = start + 2
        return DirectoryUserPage(
            users=served[start:end],
            cookie=str(end).encode() if end < len(served) else None,
        )

    ops.list_directory_users.side_effect = list_users
    ops.list_directory_groups.return_value = DirectoryGroupPage(
        groups=[group(sid) for sid in GROUP_MEMBERS], cookie=None
    )
    ops.find_directory_group.side_effect = lambda *, base_dn, sid: (  # noqa: ARG005
        group(sid) if sid in GROUP_MEMBERS else None
    )
    ops.list_group_member_sids.side_effect = lambda *, base_dn, group: GROUP_MEMBERS[  # noqa: ARG005
        group.sid
    ]
    return ops
