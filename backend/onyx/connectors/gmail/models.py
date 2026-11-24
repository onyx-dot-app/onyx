from enum import Enum

from pydantic import BaseModel


class GroupRole(str, Enum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"


class GroupMembers(BaseModel):
    # Lowercased addresses.
    user_emails: frozenset[str]
    # A group can hold every user of the Workspace account as one member, which
    # the directory lists with no address.
    has_all_account_users: bool
