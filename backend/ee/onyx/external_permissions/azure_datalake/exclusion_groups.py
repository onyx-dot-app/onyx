"""The exclusion groups of an Entra tenant, such as "the tenant minus ACL
Group A". See ``microsoft_utils.exclusion_groups``."""

from ee.onyx.external_permissions.microsoft_utils.exclusion_groups import (
    ExclusionGroupCodec,
)
from ee.onyx.external_permissions.microsoft_utils.exclusion_groups import (
    exclusion_group_members as exclusion_group_members,
)
from ee.onyx.external_permissions.microsoft_utils.principal_sets import PrincipalTerm

EXCLUSION_GROUP_PREFIX = "entra_except"
_CODEC = ExclusionGroupCodec(
    prefix=EXCLUSION_GROUP_PREFIX, directory_base_prefix="tenant."
)


def exclusion_group_id(term: PrincipalTerm, tenant_id: str) -> str:
    """``entra_except:<base>:<excluded users>:<excluded groups>``, where the
    base is a group id or ``tenant.<tenant id>``."""
    return _CODEC.group_id(term, tenant_id)


def parse_exclusion_group_id(group_id: str, tenant_id: str) -> PrincipalTerm | None:
    """The term of an exclusion group id. None for an id of another form or
    of another tenant."""
    return _CODEC.parse(group_id, tenant_id)
