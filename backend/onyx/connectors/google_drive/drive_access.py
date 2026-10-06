"""Choosing which identity to impersonate for a shared drive, and telling an
unreachable drive apart from an empty one.

A shared drive organizer (Manager in the UI) can always open folders with
limited access inside that drive, and that access cannot be revoked. So one
organizer pass returns everything, where a union over arbitrary members can
silently miss restricted folders. Probes against the onyx-test tenant measured
the gap: the organizer saw 25 items in shared_drive_1, a reader saw 23.

Nothing here calls the retrieval path; it only decides who should do the call.
"""

from collections.abc import Callable, Iterator
from enum import Enum

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]
from pydantic import BaseModel

from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.utils.logger import setup_logger

logger = setup_logger()

# permissions.list needs the file id of the drive itself; `role` is in
# PERMISSION_FULL_DESCRIPTION but this call only needs these three fields.
DRIVE_MEMBER_FIELDS = "permissions(emailAddress, type, role), nextPageToken"

# What a requested target probe needs to decide who should crawl it.
TARGET_PROBE_FIELDS = "id, mimeType, driveId, owners(emailAddress)"


class DriveRole(str, Enum):
    """Shared drive membership roles, most privileged first.

    Only ORGANIZER carries Google's guarantee of seeing limited-access folders.
    """

    ORGANIZER = "organizer"
    FILE_ORGANIZER = "fileOrganizer"
    WRITER = "writer"
    COMMENTER = "commenter"
    READER = "reader"


# Descending privilege. Used to pick the best available principal when a drive
# has no organizer we can impersonate.
_ROLE_PREFERENCE = (
    DriveRole.ORGANIZER,
    DriveRole.FILE_ORGANIZER,
    DriveRole.WRITER,
    DriveRole.COMMENTER,
    DriveRole.READER,
)


class PrincipalType(str, Enum):
    USER = "user"
    GROUP = "group"
    DOMAIN = "domain"
    ANYONE = "anyone"


class DriveReachability(str, Enum):
    REACHABLE = "reachable"
    # drives.get 404s. An empty files.list for such a drive means "cannot see
    # it", not "it is empty", and must never drive a prune.
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class DriveMember(BaseModel):
    email: str | None
    principal_type: PrincipalType
    role: DriveRole


class OrganizerChoice(BaseModel):
    """Who to impersonate for a drive, and whether the result can be trusted."""

    drive_id: str
    email: str | None
    role: DriveRole | None
    # True only when the chosen principal is an organizer, which is the only
    # role guaranteed to see limited-access folders. Callers must not prune
    # based on a listing produced with complete=False.
    complete: bool
    reason: str


def _parse_member(raw: dict[str, object]) -> DriveMember | None:
    """Skip principals with a role or type Google added after this was written."""
    raw_type = raw.get("type")
    raw_role = raw.get("role")
    try:
        principal_type = PrincipalType(raw_type)
        role = DriveRole(raw_role)
    except ValueError:
        logger.debug("Skipping drive member with type=%s role=%s", raw_type, raw_role)
        return None

    email = raw.get("emailAddress")
    return DriveMember(
        email=email if isinstance(email, str) else None,
        principal_type=principal_type,
        role=role,
    )


def list_drive_members(admin_drive_service: object, drive_id: str) -> list[DriveMember]:
    """Read a shared drive's membership using domain admin access.

    This works even for drives the admin is not a member of, which is the point:
    files.list returns 403 teamDriveMembershipRequired there, but permissions.list
    with useDomainAdminAccess still names the organizer to impersonate.

    Returns an empty list for drives outside our domain, where the call 404s.
    Any other failure is raised: an auth or server error is not evidence that a
    drive has no members, and swallowing it would silently skip the drive.
    """
    members: list[DriveMember] = []
    try:
        for raw in execute_paginated_retrieval(
            retrieval_function=admin_drive_service.permissions().list,  # ty: ignore[unresolved-attribute]
            list_key="permissions",
            fileId=drive_id,
            useDomainAdminAccess=True,
            supportsAllDrives=True,
            fields=DRIVE_MEMBER_FIELDS,
        ):
            member = _parse_member(raw)
            if member is not None:
                members.append(member)
    except HttpError as error:
        if error.resp.status != 404:
            raise
        # Domain admin access only applies to drives we own, so a drive in a
        # foreign domain always answers 404 here.
        logger.info(
            "Drive %s is not in this domain; it has no members we can read.",
            drive_id,
        )
        return []

    return members


def list_group_member_emails(admin_service: object, group_email: str) -> list[str]:
    """Direct user members of a group. Nested groups are not expanded."""
    return [
        member["email"]
        for member in execute_paginated_retrieval(
            retrieval_function=admin_service.members().list,  # ty: ignore[unresolved-attribute]
            list_key="members",
            groupKey=group_email,
            fields="members(email, type), nextPageToken",
        )
        if member.get("type") == "USER" and member.get("email")
    ]


def can_list_drive(drive_service: object, drive_id: str) -> bool:
    """One-item listing as the impersonated user. False on any auth or access
    failure, so the caller moves to the next candidate."""
    try:
        drive_service.files().list(  # ty: ignore[unresolved-attribute]
            corpora="drive",
            driveId=drive_id,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageSize=1,
            fields="files(id)",
        ).execute()
    except (HttpError, RefreshError) as error:
        logger.info("Listing drive %s failed: %s", drive_id, error)
        return False
    return True


def probe_target(drive_service: object, target_id: str) -> dict[str, object] | None:
    """Metadata of a requested drive or folder, or None if this user cannot
    see it. A user without access gets 404, so a miss is cheap and unambiguous.
    """
    try:
        request = drive_service.files().get(  # ty: ignore[unresolved-attribute]
            fileId=target_id,
            supportsAllDrives=True,
            fields=TARGET_PROBE_FIELDS,
        )
        return request.execute()
    except HttpError as error:
        if error.resp.status in (403, 404):
            return None
        raise
    except RefreshError:
        return None


def internal_principals_of(
    drive_service: object,
    target_id: str,
    google_domain: str,
    expand_group: Callable[[str], list[str]],
) -> list[str] | None:
    """In-domain users and group members named on a target's own permissions.

    Read as a user who can see the target, without domain admin access, which
    is what works for externally owned objects. None when the list cannot be
    read, so the caller falls back to a wider union.
    """
    try:
        permissions = list(
            execute_paginated_retrieval(
                retrieval_function=drive_service.permissions().list,  # ty: ignore[unresolved-attribute]
                list_key="permissions",
                fileId=target_id,
                supportsAllDrives=True,
                fields=DRIVE_MEMBER_FIELDS,
            )
        )
    except (HttpError, RefreshError) as error:
        logger.info("Cannot read permissions of %s: %s", target_id, error)
        return None

    emails: set[str] = set()
    for raw in permissions:
        email = raw.get("emailAddress")
        if not isinstance(email, str):
            continue
        if raw.get("type") == PrincipalType.USER.value:
            emails.add(email)
        elif raw.get("type") == PrincipalType.GROUP.value:
            try:
                emails.update(expand_group(email))
            except Exception:
                logger.exception("Could not expand group %s on %s", email, target_id)
    return sorted(email for email in emails if _in_domain(email, google_domain))


def check_drive_reachable(drive_service: object, drive_id: str) -> DriveReachability:
    """Distinguish a drive we cannot see from a drive with no files.

    shared_drive_3 in the test tenant shows why this matters: files.list returns
    success with zero items while drives.get 404s. Treating that as an empty
    drive would prune every document previously indexed from it.
    """
    try:
        drive_service.drives().get(  # ty: ignore[unresolved-attribute]
            driveId=drive_id, fields="id"
        ).execute()
    except HttpError as error:
        if error.resp.status == 404:
            return DriveReachability.UNREACHABLE
        logger.warning(
            "Unexpected error checking reachability of drive %s: %s", drive_id, error
        )
        return DriveReachability.UNKNOWN
    return DriveReachability.REACHABLE


def _emails_of_type(
    members: list[DriveMember],
    role: DriveRole,
    principal_type: PrincipalType,
) -> list[str]:
    # Sorted so a resumed run makes the same choice as the original.
    return sorted(
        {
            member.email
            for member in members
            if member.role is role
            and member.principal_type is principal_type
            and member.email is not None
        }
    )


def _candidate_emails(
    members: list[DriveMember],
    role: DriveRole,
    google_domain: str,
    expand_group: Callable[[str], list[str]],
) -> Iterator[str]:
    """In-domain emails holding `role`, direct members before group members.

    Lazy on purpose. Groups are expanded only once the direct members are
    exhausted, so a Directory API outage cannot stop us from picking a direct
    organizer that would have worked.

    External principals are dropped throughout: an account outside the domain
    cannot be impersonated, so naming it would only fail later.
    """
    seen: set[str] = set()

    for email in _emails_of_type(members, role, PrincipalType.USER):
        if _in_domain(email, google_domain) and email not in seen:
            seen.add(email)
            yield email

    for group_email in _emails_of_type(members, role, PrincipalType.GROUP):
        try:
            group_members = expand_group(group_email)
        except Exception:
            logger.exception(
                "Could not expand group %s while selecting an organizer.", group_email
            )
            continue
        for email in sorted(group_members):
            if _in_domain(email, google_domain) and email not in seen:
                seen.add(email)
                yield email


def _in_domain(email: str, google_domain: str) -> bool:
    return email.lower().endswith(f"@{google_domain.lower()}")


def select_drive_organizer(
    drive_id: str,
    members: list[DriveMember],
    google_domain: str,
    expand_group: Callable[[str], list[str]],
    can_list_drive: Callable[[str], bool],
) -> OrganizerChoice:
    """Pick the identity to impersonate for a shared drive.

    Walks roles from organizer downward, and within a role takes direct user
    members before group members. Every candidate is verified with a cheap
    listing before it is returned, because a named organizer can still fail to
    impersonate (suspended account, delegation gap).
    """
    for role in _ROLE_PREFERENCE:
        for email in _candidate_emails(members, role, google_domain, expand_group):
            if not can_list_drive(email):
                logger.info(
                    "Candidate %s holds %s on drive %s but cannot list it; trying next.",
                    email,
                    role.value,
                    drive_id,
                )
                continue

            complete = role is DriveRole.ORGANIZER
            if not complete:
                logger.warning(
                    "Drive %s has no usable organizer; falling back to %s (%s). "
                    "Limited-access folders may be missed.",
                    drive_id,
                    email,
                    role.value,
                )
            return OrganizerChoice(
                drive_id=drive_id,
                email=email,
                role=role,
                complete=complete,
                reason=f"verified {role.value}",
            )

    logger.warning(
        "No impersonable principal found for drive %s among %s members.",
        drive_id,
        len(members),
    )
    return OrganizerChoice(
        drive_id=drive_id,
        email=None,
        role=None,
        complete=False,
        reason="no impersonable principal",
    )
