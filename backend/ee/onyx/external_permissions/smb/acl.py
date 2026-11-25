"""Who an NTFS access list (DACL) lets read a file or list a folder.

NTFS stores inherited entries on each child, so a file's own list gives its
full NTFS access. Windows reads the entries in stored order and stops at the
first one that decides, so a deny entry removes its principal from every
allow entry after it, and from none before it.

Onyx can name only the principals of the domain. An allow entry for another
principal grants nothing, which fails closed. A deny entry for a principal
Onyx cannot name could deny anyone, so the whole list then grants nothing.
"""

from enum import Enum

from pydantic import BaseModel

from ee.onyx.external_permissions.microsoft_utils.principal_sets import (
    EMPTY_SET,
    EVERYONE_TERM,
    PrincipalSet,
    PrincipalTerm,
    everyone_term,
    exclude,
    group_term,
    simplify,
    user_term,
)
from ee.onyx.external_permissions.smb.directory import ActiveDirectory
from onyx.connectors.smb.security_descriptor import (
    Ace,
    AceKind,
    SecurityDescriptor,
)
from onyx.connectors.smb.sid import domain_sid_of, normalize_sid

# FILE_READ_DATA on a file and FILE_LIST_DIRECTORY on a folder.
_READ_DATA = 0x00000001
_GENERIC_READ = 0x80000000
_GENERIC_ALL = 0x10000000
READ_MASK = _READ_DATA | _GENERIC_READ | _GENERIC_ALL

_EVERYONE_SID = "S-1-1-0"
_AUTHENTICATED_USERS_SID = "S-1-5-11"
_DOMAIN_USERS_RID = 513
# Service and placeholder principals: no person signs in as one.
_SERVICE_SIDS = frozenset(
    {
        "S-1-5-18",  # SYSTEM
        "S-1-3-0",  # CREATOR OWNER
        "S-1-3-1",  # CREATOR GROUP
        "S-1-3-4",  # OWNER RIGHTS
    }
)


class PrincipalClass(str, Enum):
    # Everyone, Authenticated Users and Domain Users: every user of the domain.
    EVERYONE = "everyone"
    USER = "user"
    GROUP = "group"
    SERVICE = "service"
    # A local group or account of the file server (BUILTIN groups included),
    # a principal of another domain, or a deleted one. LDAP cannot name it.
    UNKNOWN = "unknown"


class UnresolvableDenyError(Exception):
    """A deny entry names a principal Onyx cannot resolve to users."""


class DaclReaders(BaseModel):
    principals: PrincipalSet
    # The SIDs of allow entries that grant read access to a principal Onyx
    # cannot name. They get no access through permission sync.
    unknown_allow_sids: frozenset[str] = frozenset()


def classify(sid: str, directory: ActiveDirectory) -> PrincipalClass:
    sid = normalize_sid(sid)
    domain_sid: str = directory.domain_sid()
    if sid in (
        _EVERYONE_SID,
        _AUTHENTICATED_USERS_SID,
        f"{domain_sid}-{_DOMAIN_USERS_RID}",
    ):
        return PrincipalClass.EVERYONE
    if sid in _SERVICE_SIDS:
        return PrincipalClass.SERVICE
    # A domain controller also lists BUILTIN groups. Those are its own, not
    # the file server's, so only the domain's SIDs are looked up.
    if domain_sid_of(sid) != domain_sid:
        return PrincipalClass.UNKNOWN
    if directory.is_user(sid):
        return PrincipalClass.USER
    if directory.group(sid) is not None:
        return PrincipalClass.GROUP
    return PrincipalClass.UNKNOWN


def _allowed_term(
    ace: Ace,
    principal_class: PrincipalClass,
    denied_users: frozenset[str],
    denied_groups: frozenset[str],
    directory: ActiveDirectory,
) -> PrincipalTerm | None:
    sid: str = normalize_sid(ace.sid)
    if principal_class is PrincipalClass.EVERYONE:
        term: PrincipalTerm = (
            everyone_term(denied_users, denied_groups)
            if denied_users or denied_groups
            else EVERYONE_TERM
        )
        return term
    base: PrincipalTerm = (
        user_term(sid) if principal_class is PrincipalClass.USER else group_term(sid)
    )
    return exclude(base, denied_users, denied_groups, directory)


def dacl_readers(
    descriptor: SecurityDescriptor, directory: ActiveDirectory
) -> DaclReaders:
    """The principals the access list lets read. Raises
    ``UnresolvableDenyError`` when it cannot tell whom a deny entry stops."""
    if not descriptor.dacl_present:
        # No list at all gives everyone full access.
        return DaclReaders(principals=frozenset({EVERYONE_TERM}))
    denied_users: set[str] = set()
    denied_groups: set[str] = set()
    terms: list[PrincipalTerm] = []
    unknown_allow_sids: set[str] = set()
    for ace in descriptor.aces:
        if ace.inherit_only or not ace.mask & READ_MASK:
            continue
        principal_class: PrincipalClass = classify(ace.sid, directory)
        if ace.kind is AceKind.DENY:
            # A deny entry with a condition counts in full: Onyx cannot tell
            # when it applies.
            if principal_class is PrincipalClass.SERVICE:
                continue
            if principal_class is PrincipalClass.EVERYONE:
                # No later entry can let anyone in.
                break
            if principal_class is PrincipalClass.UNKNOWN:
                raise UnresolvableDenyError(
                    f"A deny entry names {ace.sid}, which the domain does not know."
                )
            if principal_class is PrincipalClass.USER:
                denied_users.add(normalize_sid(ace.sid))
            else:
                denied_groups.add(normalize_sid(ace.sid))
            continue
        # An allow entry with a condition grants nothing here.
        if ace.qualified or principal_class is PrincipalClass.SERVICE:
            continue
        if principal_class is PrincipalClass.UNKNOWN:
            unknown_allow_sids.add(normalize_sid(ace.sid))
            continue
        term: PrincipalTerm | None = _allowed_term(
            ace,
            principal_class,
            frozenset(denied_users),
            frozenset(denied_groups),
            directory,
        )
        if term is not None:
            terms.append(term)
    return DaclReaders(
        principals=simplify(terms) if terms else EMPTY_SET,
        unknown_allow_sids=frozenset(unknown_allow_sids),
    )
