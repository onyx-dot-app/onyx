from enum import Enum

from pydantic import BaseModel


class GroupViewSetting(str, Enum):
    """The Groups Settings API values of "who can view conversations"."""

    ANYONE_CAN_VIEW = "ANYONE_CAN_VIEW"
    ALL_IN_DOMAIN_CAN_VIEW = "ALL_IN_DOMAIN_CAN_VIEW"
    ALL_MEMBERS_CAN_VIEW = "ALL_MEMBERS_CAN_VIEW"
    ALL_MANAGERS_CAN_VIEW = "ALL_MANAGERS_CAN_VIEW"
    ALL_OWNERS_CAN_VIEW = "ALL_OWNERS_CAN_VIEW"


class GroupRole(str, Enum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    MEMBER = "MEMBER"


class GroupSettings(BaseModel):
    is_collaborative_inbox: bool
    # None for a value this code does not know: nobody reads the group's mail.
    who_can_view: GroupViewSetting | None
