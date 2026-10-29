"""Sets of Entra principals, kept at group level where that stays exact.

A ``PrincipalSet`` is a union of terms. A term is one user, one group, or the
whole tenant, minus some users and the members of some groups. ACLs produce
such sets: ``other`` grants "everyone not matched by an earlier entry", and a
named user without the bit is denied even when one of their groups grants it.

Union keeps every term. Intersection keeps group level when one side holds
the other (the same group, or the whole tenant), and expands to users only
where two different groups meet. Document access has no exclusions, so a
term with exclusions becomes a synced exclusion group (``exclusion_groups``).
"""

from collections.abc import Iterable
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from onyx.access.models import ExternalAccess


class PrincipalKind(str, Enum):
    USER = "user"
    GROUP = "group"
    # Every user of the tenant: the ACL ``other`` class.
    EVERYONE = "everyone"


class PrincipalTerm(BaseModel):
    """``principal`` minus ``excluded_users`` and minus the members of
    ``excluded_groups``. A user term never carries exclusions: they are
    applied when the term is made."""

    model_config = ConfigDict(frozen=True)

    kind: PrincipalKind
    # The Entra object id. Empty for EVERYONE.
    principal_id: str = ""
    excluded_users: frozenset[str] = frozenset()
    excluded_groups: frozenset[str] = frozenset()

    @property
    def is_plain(self) -> bool:
        return not self.excluded_users and not self.excluded_groups


EVERYONE_TERM = PrincipalTerm(kind=PrincipalKind.EVERYONE)

PrincipalSet = frozenset[PrincipalTerm]
EMPTY_SET: PrincipalSet = frozenset()


class EntraDirectory(Protocol):
    """Membership answers for the tenant, each read once per sync."""

    def group_members(self, group_id: str) -> frozenset[str]:
        """The user object ids in the group, nested groups included."""
        ...

    def all_users(self) -> frozenset[str]:
        """Every user object id the tenant's ``other`` class covers."""
        ...

    def user_email(self, user_id: str) -> str | None:
        """The user's email, or None for an object that is not a user."""
        ...


class ExpansionLimitError(Exception):
    """Exact access needs more entries than one document can hold."""


# No document can list more users, so a larger group intersection fails early.
_MAX_SHARED_MEMBERS = ExternalAccess.MAX_NUM_ENTRIES


class ResolvedPrincipals(BaseModel):
    user_emails: set[str]
    group_ids: set[str]
    everyone: bool
    # Group and tenant terms with exclusions.
    exclusion_terms: set[PrincipalTerm]


def user_term(user_id: str) -> PrincipalTerm:
    return PrincipalTerm(kind=PrincipalKind.USER, principal_id=user_id)


def group_term(
    group_id: str,
    excluded_users: Iterable[str] = (),
    excluded_groups: Iterable[str] = (),
) -> PrincipalTerm:
    return PrincipalTerm(
        kind=PrincipalKind.GROUP,
        principal_id=group_id,
        excluded_users=frozenset(excluded_users),
        excluded_groups=frozenset(excluded_groups),
    )


def everyone_term(
    excluded_users: Iterable[str] = (), excluded_groups: Iterable[str] = ()
) -> PrincipalTerm:
    return PrincipalTerm(
        kind=PrincipalKind.EVERYONE,
        excluded_users=frozenset(excluded_users),
        excluded_groups=frozenset(excluded_groups),
    )


def exclude(
    term: PrincipalTerm,
    excluded_users: frozenset[str],
    excluded_groups: frozenset[str],
    directory: EntraDirectory,
) -> PrincipalTerm | None:
    """``term`` minus more principals. None when nothing is left that the
    term itself can tell, e.g. a user who is excluded."""
    if term.kind is PrincipalKind.USER:
        if term.principal_id in excluded_users:
            return None
        if any(
            term.principal_id in directory.group_members(group_id)
            for group_id in excluded_groups
        ):
            return None
        return term
    if term.kind is PrincipalKind.GROUP and term.principal_id in excluded_groups:
        return None
    return term.model_copy(
        update={
            "excluded_users": term.excluded_users | excluded_users,
            "excluded_groups": term.excluded_groups | excluded_groups,
        }
    )


def _intersect_terms(
    a: PrincipalTerm, b: PrincipalTerm, directory: EntraDirectory
) -> list[PrincipalTerm]:
    """Two group or tenant terms."""
    excluded_users = a.excluded_users | b.excluded_users
    excluded_groups = a.excluded_groups | b.excluded_groups
    if a.kind is PrincipalKind.EVERYONE:
        kept = b
    elif b.kind is PrincipalKind.EVERYONE or (
        a.kind is b.kind and a.principal_id == b.principal_id
    ):
        kept = a
    else:
        # Two different groups: only their common members are in both.
        shared: frozenset[str] = directory.group_members(
            a.principal_id
        ) & directory.group_members(b.principal_id)
        kept_users: list[PrincipalTerm] = []
        for user_id in sorted(shared):
            term = exclude(
                user_term(user_id), excluded_users, excluded_groups, directory
            )
            if term is None:
                continue
            kept_users.append(term)
            if len(kept_users) > _MAX_SHARED_MEMBERS:
                raise ExpansionLimitError(
                    f"Groups {a.principal_id} and {b.principal_id} share more than "
                    f"{_MAX_SHARED_MEMBERS} members."
                )
        return kept_users
    result = exclude(kept, excluded_users, excluded_groups, directory)
    return [] if result is None else [result]


def simplify(terms: Iterable[PrincipalTerm]) -> PrincipalSet:
    """Drops terms another term holds: everything when the whole tenant is in,
    and a term whose exclusions are a superset of a same-principal term's."""
    unique: set[PrincipalTerm] = set(terms)
    if EVERYONE_TERM in unique:
        return frozenset({EVERYONE_TERM})
    by_principal: dict[tuple[PrincipalKind, str], list[PrincipalTerm]] = {}
    for term in unique:
        by_principal.setdefault((term.kind, term.principal_id), []).append(term)
    kept: set[PrincipalTerm] = set()
    for same_principal in by_principal.values():
        for term in same_principal:
            held = any(
                other != term
                and other.excluded_users <= term.excluded_users
                and other.excluded_groups <= term.excluded_groups
                for other in same_principal
            )
            if not held:
                kept.add(term)
    return frozenset(kept)


def exclude_from_set(
    principals: PrincipalSet,
    excluded_users: frozenset[str],
    excluded_groups: frozenset[str],
    directory: EntraDirectory,
) -> PrincipalSet:
    return simplify(
        narrowed
        for term in principals
        if (narrowed := exclude(term, excluded_users, excluded_groups, directory))
        is not None
    )


def union(*sets: PrincipalSet) -> PrincipalSet:
    return simplify(term for principal_set in sets for term in principal_set)


def _in_term(user_id: str, term: PrincipalTerm, directory: EntraDirectory) -> bool:
    """Whether a user is in a group or tenant term."""
    if term.kind is PrincipalKind.GROUP and user_id not in directory.group_members(
        term.principal_id
    ):
        return False
    return (
        exclude(
            user_term(user_id), term.excluded_users, term.excluded_groups, directory
        )
        is not None
    )


def intersect(
    a: PrincipalSet, b: PrincipalSet, directory: EntraDirectory
) -> PrincipalSet:
    if a == b:
        return a
    if a == frozenset({EVERYONE_TERM}):
        return b
    if b == frozenset({EVERYONE_TERM}):
        return a
    # Users are compared as sets, so an expanded side costs one membership
    # test per user and term of the other side, not one per pair of users.
    users_a: set[str] = {t.principal_id for t in a if t.kind is PrincipalKind.USER}
    users_b: set[str] = {t.principal_id for t in b if t.kind is PrincipalKind.USER}
    others_a: list[PrincipalTerm] = [t for t in a if t.kind is not PrincipalKind.USER]
    others_b: list[PrincipalTerm] = [t for t in b if t.kind is not PrincipalKind.USER]
    users: set[str] = users_a & users_b
    users |= {
        user_id
        for user_id in users_a - users
        if any(_in_term(user_id, term, directory) for term in others_b)
    }
    users |= {
        user_id
        for user_id in users_b - users
        if any(_in_term(user_id, term, directory) for term in others_a)
    }
    return simplify(
        [
            *(user_term(user_id) for user_id in users),
            *(
                term
                for left in others_a
                for right in others_b
                for term in _intersect_terms(left, right, directory)
            ),
        ]
    )


def resolve(
    principals: PrincipalSet, directory: EntraDirectory, max_users: int
) -> ResolvedPrincipals:
    """The principals as emails, plain group ids, the whole tenant, and the
    terms with exclusions. Raises when the users pass the cap."""
    user_ids: set[str] = set()
    group_ids: set[str] = set()
    exclusion_terms: set[PrincipalTerm] = set()
    everyone: bool = False
    for term in principals:
        if term.kind is PrincipalKind.USER:
            user_ids.add(term.principal_id)
        elif not term.is_plain:
            exclusion_terms.add(term)
        elif term.kind is PrincipalKind.EVERYONE:
            everyone = True
        else:
            group_ids.add(term.principal_id)
    if len(user_ids) > max_users:
        raise ExpansionLimitError(f"Exact access needs more than {max_users} users.")
    return ResolvedPrincipals(
        user_emails={
            email
            for user_id in user_ids
            if (email := directory.user_email(user_id)) is not None
        },
        group_ids=group_ids,
        everyone=everyone,
        exclusion_terms=exclusion_terms,
    )
