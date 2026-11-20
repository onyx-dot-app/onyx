from ee.onyx.external_permissions.utils import instance_key
from onyx.access.models import ExternalAccess
from onyx.connectors.dealcloud.models import DealCloudUserGroup

_READ_ALL: str = "all"
_READ_NONE: str = "none"


def entry_type_group_id(instance: str, entry_type_id: int) -> str:
    return f"{instance}:object:{entry_type_id}"


def entry_type_access(base_url: str, entry_type_id: int) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={
            entry_type_group_id(instance_key(base_url), entry_type_id)
        },
        # Never public: every DealCloud reader signs in.
        is_public=False,
    )


def reads_every_entry(group: DealCloudUserGroup) -> bool:
    """A narrower grant has no equivalent in Onyx. Giving its group a whole
    object would show entries DealCloud hides, so only this grant counts."""
    return (
        (group.read_data or "").lower() == _READ_ALL
        and group.entry_level_capabilities.read.all_entry_lists_allowed
    )


def reads_nothing(group: DealCloudUserGroup) -> bool:
    return (group.read_data or "").lower() == _READ_NONE
