"""Who may read the files of an Egnyte folder.

Egnyte sets permissions on folders only, and a file has the permissions of its
folder. A folder listing with ``perms=true`` returns the folder's effective
grants, inherited ones included, so no inheritance is computed here. Egnyte
has no deny: a user's None does not remove what a group grants. A folder's
readers are therefore every user and group with Viewer or higher.

Administrators can read every folder, private ones included, so every folder
names the administrators group. Default groups ("All Power Users") appear in
grants by name and are not listed with the custom groups, so group sync builds
them from each user's type.

Group ids carry the domain, since two Egnyte connectors on one tenant may read
different domains.
"""

from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.access.models import ExternalAccess
from onyx.connectors.egnyte.access import EgnyteUnknownGroupError
from onyx.connectors.egnyte.models import (
    EgnyteDirectory,
    EgnytePermissions,
    EgnyteUser,
    EgnyteUserType,
)
from onyx.connectors.egnyte.source_operations import EgnyteSourceOperations
from onyx.utils.logger import setup_logger

logger = setup_logger()

READ_PERMISSIONS: frozenset[str] = frozenset({"Viewer", "Editor", "Full", "Owner"})
ADMINISTRATORS_GROUP_NAME: str = "All Administrators"
DEFAULT_GROUP_USER_TYPES: dict[str, frozenset[EgnyteUserType]] = {
    ADMINISTRATORS_GROUP_NAME: frozenset({EgnyteUserType.ADMIN}),
    "All Power Users": frozenset({EgnyteUserType.POWER}),
    "All Standard Users": frozenset({EgnyteUserType.STANDARD}),
    "All Standard Users and Power Users": frozenset(
        {EgnyteUserType.POWER, EgnyteUserType.STANDARD}
    ),
}


def default_group_id(domain: str, group_name: str) -> str:
    slug = group_name.lower().replace(" ", "-")
    return f"{domain.lower()}:default:{slug}"


def custom_group_id(domain: str, group_id: str) -> str:
    return f"{domain.lower()}:group:{group_id}"


def active_users(ops: EgnyteSourceOperations) -> list[EgnyteUser]:
    return [user for user in ops.list_users() if user.active and user.email.strip()]


def build_directory(ops: EgnyteSourceOperations) -> EgnyteDirectory:
    return EgnyteDirectory(
        emails_by_username={
            user.user_name: user.email.strip().lower() for user in active_users(ops)
        },
        group_ids_by_name={group.display_name: group.id for group in ops.list_groups()},
    )


def folder_access(
    domain: str,
    permissions: EgnytePermissions | None,
    directory: EgnyteDirectory,
) -> ExternalAccess:
    """The folder's readers, with bare group ids. None for the folders whose
    permissions Egnyte will not list ("/" and "/Private"), which only
    administrators read."""
    emails: set[str] = set()
    group_ids: set[str] = {default_group_id(domain, ADMINISTRATORS_GROUP_NAME)}
    if permissions is None:
        return ExternalAccess(
            external_user_emails=emails,
            external_user_group_ids=group_ids,
            is_public=False,
        )
    for grant in permissions.users:
        if grant.permission not in READ_PERMISSIONS:
            continue
        email = directory.emails_by_username.get(grant.subject)
        if email is None:
            # Inactive and deleted users read nothing.
            logger.info("Skipping Egnyte grant to inactive user %s", grant.subject)
            continue
        emails.add(email)
    for grant in permissions.groups:
        if grant.permission not in READ_PERMISSIONS:
            continue
        if grant.subject in DEFAULT_GROUP_USER_TYPES:
            group_ids.add(default_group_id(domain, grant.subject))
        elif grant.subject in directory.group_ids_by_name:
            group_ids.add(
                custom_group_id(domain, directory.group_ids_by_name[grant.subject])
            )
        else:
            raise EgnyteUnknownGroupError(
                f"Egnyte grants the unknown group '{grant.subject}'."
            )
    return ExternalAccess(
        external_user_emails=emails,
        external_user_group_ids=group_ids,
        is_public=False,
    )


def default_groups(domain: str, users: list[EgnyteUser]) -> list[ExternalUserGroup]:
    """The default groups, built from each active user's type."""
    return [
        ExternalUserGroup(
            id=default_group_id(domain, group_name),
            user_emails=sorted(
                {
                    user.email.strip().lower()
                    for user in users
                    if user.user_type in user_types
                }
            ),
        )
        for group_name, user_types in DEFAULT_GROUP_USER_TYPES.items()
    ]
