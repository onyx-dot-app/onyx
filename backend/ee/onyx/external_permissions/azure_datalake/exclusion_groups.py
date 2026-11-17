"""Synced groups for principal terms with exclusions, such as "the tenant
minus ACL Group A". Onyx access cannot exclude anyone, and expanding such a
term to users passes the per-document entry limit in a large tenant.

The doc sync names each term by an id that encodes it. The group sync reads
those ids back from the cc-pair's stored access and syncs each one's members,
so no other storage holds the terms. A term the doc sync names for the first
time has no members until the next group sync, so it fails closed until then.
"""

from ee.onyx.external_permissions.azure_datalake.principals import (
    EntraDirectory,
    ExpansionLimitError,
    PrincipalKind,
    PrincipalTerm,
    everyone_term,
    group_term,
)

EXCLUSION_GROUP_PREFIX = "entra_except"
# Bounds the id, which every chunk of the document stores.
MAX_EXCLUDED_PRINCIPALS = 50
_TENANT_BASE_PREFIX = "tenant."
_FIELD_SEPARATOR = ":"
_ID_SEPARATOR = ","
_FIELD_COUNT = 4


def exclusion_group_id(term: PrincipalTerm, tenant_id: str) -> str:
    """``entra_except:<base>:<excluded users>:<excluded groups>``, where the
    base is a group id or ``tenant.<tenant id>``."""
    excluded_count: int = len(term.excluded_users) + len(term.excluded_groups)
    if excluded_count > MAX_EXCLUDED_PRINCIPALS:
        raise ExpansionLimitError(
            f"An ACL term excludes {excluded_count} principals, more than "
            f"{MAX_EXCLUDED_PRINCIPALS}."
        )
    base: str = (
        f"{_TENANT_BASE_PREFIX}{tenant_id}"
        if term.kind is PrincipalKind.EVERYONE
        else term.principal_id
    )
    return _FIELD_SEPARATOR.join(
        [
            EXCLUSION_GROUP_PREFIX,
            base,
            _ID_SEPARATOR.join(sorted(term.excluded_users)),
            _ID_SEPARATOR.join(sorted(term.excluded_groups)),
        ]
    ).lower()


def _ids(field: str) -> frozenset[str]:
    return frozenset(item for item in field.split(_ID_SEPARATOR) if item)


def parse_exclusion_group_id(group_id: str, tenant_id: str) -> PrincipalTerm | None:
    """The term of an exclusion group id. None for an id of another form or
    of another tenant."""
    fields: list[str] = group_id.split(_FIELD_SEPARATOR)
    if len(fields) != _FIELD_COUNT or fields[0] != EXCLUSION_GROUP_PREFIX:
        return None
    _, base, excluded_users, excluded_groups = fields
    if not base.startswith(_TENANT_BASE_PREFIX):
        return group_term(base, _ids(excluded_users), _ids(excluded_groups))
    if base.removeprefix(_TENANT_BASE_PREFIX) != tenant_id:
        return None
    return everyone_term(_ids(excluded_users), _ids(excluded_groups))


def exclusion_group_members(
    term: PrincipalTerm, directory: EntraDirectory
) -> frozenset[str]:
    members: frozenset[str] = (
        directory.all_users()
        if term.kind is PrincipalKind.EVERYONE
        else directory.group_members(term.principal_id)
    )
    excluded: set[str] = set(term.excluded_users)
    for group_id in term.excluded_groups:
        excluded |= directory.group_members(group_id)
    return members - excluded
