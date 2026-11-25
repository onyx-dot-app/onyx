"""The exclusion groups of an Active Directory domain, such as "the domain
minus the group a deny entry names". See ``microsoft_utils.exclusion_groups``."""

from ee.onyx.external_permissions.microsoft_utils.exclusion_groups import (
    ExclusionGroupCodec,
)
from ee.onyx.external_permissions.microsoft_utils.principal_sets import (
    PrincipalTerm,
)
from onyx.connectors.smb.sid import normalize_sid

EXCLUSION_GROUP_PREFIX = "ad_except"
_CODEC = ExclusionGroupCodec(
    prefix=EXCLUSION_GROUP_PREFIX, directory_base_prefix="domain."
)


def exclusion_group_id(term: PrincipalTerm, domain_sid: str) -> str:
    """``ad_except:<base>:<excluded users>:<excluded groups>``, where the base
    is a group SID or ``domain.<domain SID>``."""
    return _CODEC.group_id(term, domain_sid)


def parse_exclusion_group_id(group_id: str, domain_sid: str) -> PrincipalTerm | None:
    """The term of an exclusion group id, with its SIDs in upper case. None
    for an id of another form or of another domain."""
    term: PrincipalTerm | None = _CODEC.parse(group_id.lower(), domain_sid.lower())
    if term is None:
        return None
    return term.model_copy(
        update={
            "principal_id": normalize_sid(term.principal_id),
            "excluded_users": frozenset(map(normalize_sid, term.excluded_users)),
            "excluded_groups": frozenset(map(normalize_sid, term.excluded_groups)),
        }
    )
