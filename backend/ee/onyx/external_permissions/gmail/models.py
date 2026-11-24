from enum import Enum


class GroupViewSetting(str, Enum):
    """The Groups Settings API values of "who can view conversations"."""

    ANYONE_CAN_VIEW = "ANYONE_CAN_VIEW"
    ALL_IN_DOMAIN_CAN_VIEW = "ALL_IN_DOMAIN_CAN_VIEW"
    ALL_MEMBERS_CAN_VIEW = "ALL_MEMBERS_CAN_VIEW"
    ALL_MANAGERS_CAN_VIEW = "ALL_MANAGERS_CAN_VIEW"
    ALL_OWNERS_CAN_VIEW = "ALL_OWNERS_CAN_VIEW"
