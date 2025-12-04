from collections import defaultdict

from jira import JIRA
from jira.resources import PermissionScheme
from pydantic import ValidationError

from ee.onyx.external_permissions.jira.models import Holder
from ee.onyx.external_permissions.jira.models import Permission
from ee.onyx.external_permissions.jira.models import User
from onyx.access.models import ExternalAccess
from onyx.utils.logger import setup_logger

HolderMap = dict[str, list[Holder]]


logger = setup_logger()


def _build_holder_map(permissions: list[dict]) -> dict[str, list[Holder]]:
    """
    A "Holder" in JIRA is a person / entity who "holds" the corresponding permission.
    It can have different types. They can be one of (but not limited to):
        - user (an explicitly whitelisted user)
        - projectRole (for project level "roles")
        - reporter (the reporter of an issue)

    A "Holder" usually has following structure:
        - `{ "type": "user", "value": "$USER_ID", "user": { .. }, .. }`
        - `{ "type": "projectRole", "value": "$PROJECT_ID", ..  }`

    When we fetch the PermissionSchema from JIRA, we retrieve a list of "Holder"s.
    The list of "Holder"s can have multiple "Holder"s of the same type in the list (e.g., you can have two `"type": "user"`s in
    there, each corresponding to a different user).
    This function constructs a map of "Holder" types to a list of the "Holder"s which contained that type.

    Returns:
        A dict from the "Holder" type to the actual "Holder" instance.

    Example:
        ```
        {
            "user": [
                { "type": "user", "value": "10000", "user": { .. }, .. },
                { "type": "user", "value": "10001", "user": { .. }, .. },
            ],
            "projectRole": [
                { "type": "projectRole", "value": "10010", ..  },
                { "type": "projectRole", "value": "10011", ..  },
            ],
            "applicationRole": [
                { "type": "applicationRole" },
            ],
            ..
        }
        ```
    """

    holder_map: defaultdict[str, list[Holder]] = defaultdict(list)

    for raw_perm in permissions:
        if not hasattr(raw_perm, "raw"):
            logger.warning(f"Expected a 'raw' field, but none was found: {raw_perm=}")
            continue

        permission = Permission(**raw_perm.raw)

        # We only care about ability to browse through projects + issues (not other permissions such as read/write).
        if permission.permission != "BROWSE_PROJECTS":
            continue

        # In order to associate this permission to some Atlassian entity, we need the "Holder".
        # If this doesn't exist, then we cannot associate this permission to anyone; just skip.
        if not permission.holder:
            logger.warning(
                f"Expected to find a permission holder, but none was found: {permission=}"
            )
            continue

        type = permission.holder.get("type")
        if not type:
            logger.warning(
                f"Expected to find the type of permission holder, but none was found: {permission=}"
            )
            continue

        holder_map[type].append(permission.holder)

    return holder_map


def _get_user_emails(user_holders: list[Holder]) -> list[str]:
    emails = []

    for user_holder in user_holders:
        if "user" not in user_holder:
            continue
        raw_user_dict = user_holder["user"]

        try:
            user_model = User.model_validate(raw_user_dict)
        except ValidationError:
            logger.error(
                "Expected to be able to serialize the raw-user-dict into an instance of `User`, but validation failed;"
                f"{raw_user_dict=}"
            )
            continue

        emails.append(user_model.email_address)

    return emails


def _get_user_emails_and_groups_from_project_roles(
    jira_client: JIRA,
    jira_project: str,
    project_role_holders: list[Holder],
) -> tuple[list[str], list[str]]:
    """
    Get user emails and group names from project roles.
    Returns a tuple of (emails, group_names).
    """
    # Get role IDs - Cloud uses "value", Data Center uses "parameter"
    role_ids = []
    for holder in project_role_holders:
        role_id = holder.get("value") or holder.get("parameter")
        if role_id:
            role_ids.append(role_id)
        else:
            logger.warning(f"No value or parameter in projectRole holder: {holder}")

    roles = [
        jira_client.project_role(project=jira_project, id=role_id)
        for role_id in role_ids
    ]

    emails = []
    groups = []

    for role in roles:
        if not hasattr(role, "actors"):
            logger.warning(f"Project role {role} has no actors attribute")
            continue

        for actor in role.actors:
            # Handle group actors
            if hasattr(actor, "actorGroup"):
                group_name = getattr(actor.actorGroup, "name", None) or getattr(
                    actor.actorGroup, "displayName", None
                )
                if group_name:
                    groups.append(group_name)
                continue

            # Handle user actors
            if hasattr(actor, "actorUser"):
                account_id = getattr(actor.actorUser, "accountId", None)
                if not account_id:
                    logger.error(f"No accountId in actorUser: {actor.actorUser}")
                    continue

                user = jira_client.user(id=account_id)
                if not hasattr(user, "accountType") or user.accountType != "atlassian":
                    continue

                if not hasattr(user, "emailAddress"):
                    msg = f"User's email address was not able to be retrieved;  {actor.actorUser.accountId=}"
                    if hasattr(user, "displayName"):
                        msg += f" {actor.displayName=}"
                    logger.warning(msg)
                    continue

                emails.append(user.emailAddress)
                continue

            logger.debug(f"Skipping actor type: {actor}")

    return emails, groups


def _build_external_access_from_holder_map(
    jira_client: JIRA, jira_project: str, holder_map: HolderMap
) -> ExternalAccess:
    """
    Build ExternalAccess from the holder map.

    Holder types handled:
        - "anyone": Public project, anyone can access
        - "applicationRole": All users with a Jira license can access (treated as public)
        - "user": Specific users with access
        - "projectRole": Project roles containing users and/or groups
        - "group": Groups directly assigned in the permission scheme
    """
    # Public access - anyone can view
    if "anyone" in holder_map:
        return ExternalAccess(
            external_user_emails=set(), external_user_group_ids=set(), is_public=True
        )

    # applicationRole means all users with a Jira license can access - treat as public
    if "applicationRole" in holder_map:
        return ExternalAccess(
            external_user_emails=set(), external_user_group_ids=set(), is_public=True
        )

    # Get emails from explicit user holders
    user_emails = (
        _get_user_emails(user_holders=holder_map["user"])
        if "user" in holder_map
        else []
    )

    # Get emails and groups from project roles
    project_role_user_emails: list[str] = []
    project_role_groups: list[str] = []
    if "projectRole" in holder_map:
        project_role_user_emails, project_role_groups = (
            _get_user_emails_and_groups_from_project_roles(
                jira_client=jira_client,
                jira_project=jira_project,
                project_role_holders=holder_map["projectRole"],
            )
        )

    # Get groups directly assigned in permission scheme (common in Data Center)
    # Format: {'type': 'group', 'parameter': 'group-name', 'expand': 'group'}
    direct_groups: list[str] = []
    if "group" in holder_map:
        for group_holder in holder_map["group"]:
            group_name = group_holder.get("parameter") or group_holder.get("value")
            if group_name:
                direct_groups.append(group_name)

    external_user_emails = set(user_emails + project_role_user_emails)
    external_user_group_ids = set(project_role_groups + direct_groups)

    return ExternalAccess(
        external_user_emails=external_user_emails,
        external_user_group_ids=external_user_group_ids,
        is_public=False,
    )


def get_project_permissions(
    jira_client: JIRA,
    jira_project: str,
) -> ExternalAccess | None:
    project_permissions: PermissionScheme = jira_client.project_permissionscheme(
        project=jira_project
    )

    if not hasattr(project_permissions, "permissions"):
        logger.error(f"Project {jira_project} has no permissions attribute")
        return None

    if not isinstance(project_permissions.permissions, list):
        logger.error(f"Project {jira_project} permissions is not a list")
        return None

    holder_map = _build_holder_map(permissions=project_permissions.permissions)

    return _build_external_access_from_holder_map(
        jira_client=jira_client, jira_project=jira_project, holder_map=holder_map
    )
