from ee.onyx.configs.app_configs import CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC
from ee.onyx.external_permissions.confluence.constants import ALL_CONF_EMAILS_GROUP_NAME
from ee.onyx.external_permissions.confluence.constants import REQUEST_PAGINATION_LIMIT
from ee.onyx.external_permissions.confluence.constants import VIEWSPACE_PERMISSION_TYPE
from onyx.access.models import ExternalAccess
from onyx.connectors.confluence.onyx_confluence import (
    get_user_email_from_username__server,
)
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.utils.logger import setup_logger


logger = setup_logger()


def _get_server_space_permissions(
    confluence_client: OnyxConfluence, space_key: str
) -> ExternalAccess:
    space_permissions = confluence_client.get_all_space_permissions_server(
        space_key=space_key
    )

    viewspace_permissions = []
    for permission_category in space_permissions:
        if permission_category.get("type") == VIEWSPACE_PERMISSION_TYPE:
            viewspace_permissions.extend(
                permission_category.get("spacePermissions", [])
            )

    is_public = False
    user_names = set()
    group_names = set()
    for permission in viewspace_permissions:
        if user_name := permission.get("userName"):
            user_names.add(user_name)
        if group_name := permission.get("groupName"):
            group_names.add(group_name)

        # It seems that if anonymous access is turned on for the site and space,
        # then the space is publicly accessible.
        # For confluence server, we make a group that contains all users
        # that exist in confluence and then just add that group to the space permissions
        # if anonymous access is turned on for the site and space or we set is_public = True
        # if they set the env variable CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC to True so
        # that we can support confluence server deployments that want anonymous access
        # to be public (we cant test this because its paywalled)
        if user_name is None and group_name is None:
            # Defaults to False
            if CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC:
                is_public = True
            else:
                group_names.add(ALL_CONF_EMAILS_GROUP_NAME)

    user_emails = set()
    for user_name in user_names:
        user_email = get_user_email_from_username__server(confluence_client, user_name)
        if user_email:
            user_emails.add(user_email)
        else:
            logger.warning(f"Email for user {user_name} not found in Confluence")

    if not user_emails and not group_names:
        logger.warning(
            "No user emails or group names found in Confluence space permissions"
            f"\nSpace key: {space_key}"
            f"\nSpace permissions: {space_permissions}"
        )

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_names,
        is_public=is_public,
    )


def _get_cloud_space_permissions(
    confluence_client: OnyxConfluence, space_key: str
) -> ExternalAccess:
    space_permissions_result = confluence_client.get_space(
        space_key=space_key, expand="permissions"
    )
    space_permissions = space_permissions_result.get("permissions", [])

    user_emails = set()
    group_names = set()
    is_externally_public = False
    for permission in space_permissions:
        subs = permission.get("subjects")
        if subs:
            # If there are subjects, then there are explicit users or groups with access
            if email := subs.get("user", {}).get("results", [{}])[0].get("email"):
                user_emails.add(email)
            if group_name := subs.get("group", {}).get("results", [{}])[0].get("name"):
                group_names.add(group_name)
        else:
            # If there are no subjects, then the permission is for everyone
            if permission.get("operation", {}).get(
                "operation"
            ) == "read" and permission.get("anonymousAccess", False):
                # If the permission specifies read access for anonymous users, then
                # the space is publicly accessible
                is_externally_public = True

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_names,
        is_public=is_externally_public,
    )


def get_space_permission(
    confluence_client: OnyxConfluence,
    space_key: str,
    is_cloud: bool,
) -> ExternalAccess:
    if is_cloud:
        space_permissions = _get_cloud_space_permissions(confluence_client, space_key)
    else:
        space_permissions = _get_server_space_permissions(confluence_client, space_key)

    if (
        not space_permissions.is_public
        and not space_permissions.external_user_emails
        and not space_permissions.external_user_group_ids
    ):
        logger.warning(
            f"No permissions found for space '{space_key}'. This is very unlikely "
            "to be correct and is more likely caused by an access token with "
            "insufficient permissions. Make sure that the access token has Admin "
            f"permissions for space '{space_key}'"
        )

    return space_permissions


def get_all_space_permissions(
    confluence_client: OnyxConfluence,
    is_cloud: bool,
) -> dict[str, ExternalAccess]:
    logger.debug("Getting space permissions")
    # Gets all the spaces in the Confluence instance
    all_space_keys = []
    start = 0
    while True:
        spaces_batch = confluence_client.get_all_spaces(
            start=start, limit=REQUEST_PAGINATION_LIMIT
        )
        for space in spaces_batch.get("results", []):
            all_space_keys.append(space.get("key"))

        if len(spaces_batch.get("results", [])) < REQUEST_PAGINATION_LIMIT:
            break

        start += len(spaces_batch.get("results", []))

    # Gets the permissions for each space
    logger.debug(f"Got {len(all_space_keys)} spaces from confluence")
    space_permissions_by_space_key: dict[str, ExternalAccess] = {}
    for space_key in all_space_keys:
        space_permissions = get_space_permission(confluence_client, space_key, is_cloud)

        # Stores the permissions for each space
        space_permissions_by_space_key[space_key] = space_permissions

    return space_permissions_by_space_key
