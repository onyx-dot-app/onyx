"""Choosing which identity to impersonate for a shared drive, and telling an
unreachable drive apart from an empty one.

A shared drive organizer (Manager in the UI) can always open folders with
limited access inside that drive, and that access cannot be revoked. So one
organizer pass returns everything, where a union over arbitrary members can
silently miss restricted folders. Probes against the onyx-test tenant measured
the gap: the organizer saw 25 items in shared_drive_1, a reader saw 23.

Nothing here calls the retrieval path; it only decides who should do the call.
"""

from collections.abc import Callable
from enum import Enum

from googleapiclient.errors import HttpError  # type: ignore[import-untyped]
from pydantic import BaseModel

from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.utils.logger import setup_logger

logger = setup_logger()

# permissions.list needs the file id of the drive itself; `role` is in
# PERMISSION_FULL_DESCRIPTION but this call only needs these three fields.
DRIVE_MEMBER_FIELDS = "permissions(emailAddress, type, role), nextPageToken"


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
        # 404 is the normal answer for a drive in a foreign domain; domain admin
        # access only applies to drives we own.
        logger.info(
            "Could not read members of drive %s (%s); treating as no members.",
            drive_id,
            error.resp.status,
        )
        return []

    return members


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


def _candidate_emails(
    members: list[DriveMember],
    role: DriveRole,
    google_domain: str,
    expand_group: Callable[[str], list[str]],
) -> list[str]:
    """In-domain user emails holding `role`, expanding groups into their members.

    External principals are dropped: we cannot impersonate an account outside
    the domain, so naming one as the organizer would just fail later.
    """
    emails: list[str] = []
    for member in members:
        if member.role is not role or member.email is None:
            continue
        if member.principal_type is PrincipalType.GROUP:
            emails.extend(
                email
                for email in expand_group(member.email)
                if _in_domain(email, google_domain)
            )
        elif member.principal_type is PrincipalType.USER and _in_domain(
            member.email, google_domain
        ):
            emails.append(member.email)

    # Stable order so a resumed run makes the same choice as the original.
    return sorted(dict.fromkeys(emails))


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

    Walks roles from organizer downward, and within a role prefers direct user
    members over group members. Every candidate is verified with a cheap listing
    before it is returned, because a named organizer can still fail to
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
