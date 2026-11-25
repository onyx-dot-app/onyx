"""Synced groups for principal terms with exclusions, such as "the directory
minus Group A". Onyx access cannot exclude anyone, and expanding such a term
to users passes the per-document entry limit in a large directory.

The doc sync names each term by an id that encodes it. The group sync reads
those ids back from the cc-pair's stored access and syncs each one's members,
so no other storage holds the terms. A term the doc sync names for the first
time has no members until the next group sync, so it fails closed until then.
"""

from pydantic import BaseModel, ConfigDict

from ee.onyx.external_permissions.microsoft_utils.principal_sets import (
    ExpansionLimitError,
    PrincipalDirectory,
    PrincipalKind,
    PrincipalTerm,
    everyone_term,
    group_term,
)

# Bounds the id, which every chunk of the document stores.
MAX_EXCLUDED_PRINCIPALS = 50
_FIELD_SEPARATOR = ":"
_ID_SEPARATOR = ","
_FIELD_COUNT = 4


def _ids(field: str) -> frozenset[str]:
    return frozenset(item for item in field.split(_ID_SEPARATOR) if item)


class ExclusionGroupCodec(BaseModel):
    """The id form of one kind of directory. Principal ids must hold no
    colon and no comma. Ids are compared in lower case."""

    model_config = ConfigDict(frozen=True)

    # The first field of every id, e.g. "entra_except".
    prefix: str
    # Marks a base that is the whole directory, e.g. "tenant.".
    directory_base_prefix: str

    def group_id(self, term: PrincipalTerm, directory_id: str) -> str:
        """``<prefix>:<base>:<excluded users>:<excluded groups>``, where the
        base is a group id or the directory's id after its marker."""
        excluded_count: int = len(term.excluded_users) + len(term.excluded_groups)
        if excluded_count > MAX_EXCLUDED_PRINCIPALS:
            raise ExpansionLimitError(
                f"An access term excludes {excluded_count} principals, more than "
                f"{MAX_EXCLUDED_PRINCIPALS}."
            )
        base: str = (
            f"{self.directory_base_prefix}{directory_id}"
            if term.kind is PrincipalKind.EVERYONE
            else term.principal_id
        )
        return _FIELD_SEPARATOR.join(
            [
                self.prefix,
                base,
                _ID_SEPARATOR.join(sorted(term.excluded_users)),
                _ID_SEPARATOR.join(sorted(term.excluded_groups)),
            ]
        ).lower()

    def parse(self, group_id: str, directory_id: str) -> PrincipalTerm | None:
        """The term of an exclusion group id. None for an id of another form
        or of another directory."""
        fields: list[str] = group_id.split(_FIELD_SEPARATOR)
        if len(fields) != _FIELD_COUNT or fields[0] != self.prefix:
            return None
        _, base, excluded_users, excluded_groups = fields
        if not base.startswith(self.directory_base_prefix):
            return group_term(base, _ids(excluded_users), _ids(excluded_groups))
        if base.removeprefix(self.directory_base_prefix) != directory_id:
            return None
        return everyone_term(_ids(excluded_users), _ids(excluded_groups))


def exclusion_group_members(
    term: PrincipalTerm, directory: PrincipalDirectory
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
