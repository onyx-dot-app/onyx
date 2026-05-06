from ee.onyx.configs.app_configs import CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC
from ee.onyx.external_permissions.confluence.constants import ALL_CONF_EMAILS_GROUP_NAME
from ee.onyx.external_permissions.confluence.constants import REQUEST_PAGINATION_LIMIT
from ee.onyx.external_permissions.confluence.constants import (
    SPACE_PERMISSION_OPERATION_READ,
)
from ee.onyx.external_permissions.confluence.constants import (
    SPACE_PERMISSION_SUBJECT_TYPE_GROUP,
)
from ee.onyx.external_permissions.confluence.constants import (
    SPACE_PERMISSION_SUBJECT_TYPE_USER,
)
from ee.onyx.external_permissions.confluence.constants import (
    SPACE_PERMISSION_TARGET_TYPE_SPACE,
)
from ee.onyx.external_permissions.confluence.constants import VIEWSPACE_PERMISSION_TYPE
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.onyx_confluence import (
    ConfluenceRestSpacePermissionsNotAvailableError,
)
from onyx.connectors.confluence.onyx_confluence import (
    get_user_email_from_userkey__server,
)
from onyx.connectors.confluence.onyx_confluence import (
    get_user_email_from_username__server,
)
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_OPERATION = "operation"
_OPERATIONS = "operations"


def _has_anonymous_read_permission(anonymous_permissions: list[dict]) -> bool:
    """Whether the anonymous role has 'read' on a given space.

    The DC 9.1+ anonymous-permissions endpoint can return either a flat
    list of {operation: {operationKey, targetType}} entries OR a nested
    {operations: [...]} envelope, depending on patch version. Accept both
    so a transient endpoint shape change doesn't silently disable
    anonymous-access detection.
    """
    candidates: list[dict] = []
    for entry in anonymous_permissions:
        if not isinstance(entry, dict):
            continue
        if _OPERATIONS in entry and isinstance(entry[_OPERATIONS], list):
            candidates.extend(op for op in entry[_OPERATIONS] if isinstance(op, dict))
        if _OPERATION in entry and isinstance(entry[_OPERATION], dict):
            candidates.append(entry[_OPERATION])

    return any(
        op.get("operationKey") == SPACE_PERMISSION_OPERATION_READ
        and op.get("targetType") == SPACE_PERMISSION_TARGET_TYPE_SPACE
        for op in candidates
    )


def _resolve_anonymous_access(
    confluence_client: OnyxConfluence, space_key: str
) -> tuple[bool, set[str]]:
    """Decide is_public + extra group_names contributed by anonymous access.

    Returns (is_public, extra_group_names). Mirrors the legacy JSON-RPC
    behavior: if anonymous read is enabled and
    CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC is set, mark the space public;
    otherwise add ALL_CONF_EMAILS_GROUP_NAME so authenticated Confluence
    users still see the content but external/anon users don't.
    """
    try:
        anonymous_permissions = (
            confluence_client.get_anonymous_space_permissions_server_rest(
                space_key=space_key,
            )
        )
    except InsufficientPermissionsError:
        # CONFSERVER-99908: HTTP 500 from the anonymous endpoint means the
        # bot lacks Confluence/space-admin rights. The main probe in
        # validate_confluence_perm_sync only checks the bulk endpoint, so
        # this can pass validation but fail here on every sync. Surface it
        # loudly instead of silently flagging every space as "no anonymous
        # access" -- otherwise public spaces would be hidden from users.
        raise
    except Exception as e:
        # Don't fail the whole sync over an anonymous-permissions hiccup.
        # The bulk-permissions response covers explicit grants; we only
        # lose anonymous-access detection on this one space.
        logger.warning(
            "Failed to fetch anonymous space permissions for %s: %s. "
            "Treating as 'no anonymous access' for this run.",
            space_key,
            e,
        )
        return False, set()

    if not _has_anonymous_read_permission(anonymous_permissions):
        return False, set()

    if CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC:
        return True, set()
    return False, {ALL_CONF_EMAILS_GROUP_NAME}


def _get_server_space_permissions_rest(
    confluence_client: OnyxConfluence, space_key: str
) -> ExternalAccess:
    """Confluence DC 9.1+ REST-API path for space permissions.

    Differences from the JSON-RPC shape (CONFSERVER-78176, CONFSERVER-100505):
      - flat list of {operation, subject, spaceKey, spaceId} entries.
      - groups expose subject.name directly.
      - users expose subject.userKey only -- email must be resolved
        separately via /rest/api/user?key={userKey}.
      - anonymous access is its own endpoint, not an inline row.
    """
    raw_permissions = confluence_client.get_all_space_permissions_server_rest(
        space_key=space_key
    )

    user_keys: set[str] = set()
    group_names: set[str] = set()
    for permission in raw_permissions:
        operation = permission.get("operation") or {}
        if operation.get("targetType") != SPACE_PERMISSION_TARGET_TYPE_SPACE:
            continue
        if operation.get("operationKey") != SPACE_PERMISSION_OPERATION_READ:
            continue

        subject = permission.get("subject") or {}
        subject_type = subject.get("type")
        if subject_type == SPACE_PERMISSION_SUBJECT_TYPE_USER:
            if user_key := subject.get("userKey"):
                user_keys.add(user_key)
        elif subject_type == SPACE_PERMISSION_SUBJECT_TYPE_GROUP:
            if name := subject.get("name"):
                group_names.add(name)

    is_public, extra_groups = _resolve_anonymous_access(confluence_client, space_key)
    group_names.update(extra_groups)

    user_emails: set[str] = set()
    for user_key in user_keys:
        email = get_user_email_from_userkey__server(confluence_client, user_key)
        if email:
            user_emails.add(email)
            continue
        logger.warning("Email for userKey %s not found in Confluence", user_key)

    if not user_emails and not group_names and not is_public:
        logger.warning(
            "No user emails or group names found in Confluence space "
            "permissions (REST path)\nSpace key: %s\nSpace permissions: %s",
            space_key,
            raw_permissions,
        )

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_names,
        is_public=is_public,
    )


def _get_server_space_permissions_jsonrpc(
    confluence_client: OnyxConfluence, space_key: str
) -> ExternalAccess:
    """Legacy JSON-RPC path; kept for Confluence DC < 9.1.0.

    See get_all_space_permissions_server in onyx_confluence.py for the
    failure-mode notes and WebSudo escape hatch.
    """
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
            logger.warning("Email for user %s not found in Confluence", user_name)

    if not user_emails and not group_names:
        logger.warning(
            "No user emails or group names found in Confluence space permissions"
            "\nSpace key: %s"
            "\nSpace permissions: %s",
            space_key,
            space_permissions,
        )

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_names,
        is_public=is_public,
    )


def _get_server_space_permissions(
    confluence_client: OnyxConfluence, space_key: str
) -> ExternalAccess:
    """Dispatch between the DC 9.1+ REST path and the legacy JSON-RPC path.

    The JSON-RPC path is fragile on modern Confluence (Secure Administrator
    Sessions / WebSudo intercepts admin JSON-RPC calls -- see the
    get_all_space_permissions_server docstring). Wherever the REST API
    is available we prefer it.
    """
    if confluence_client.supports_rest_space_permissions():
        try:
            return _get_server_space_permissions_rest(confluence_client, space_key)
        except ConfluenceRestSpacePermissionsNotAvailableError as e:
            # serverInfo lied / custom build / plugin disabled; fall back.
            logger.info(
                "Confluence reports a version that should support REST "
                "space-permissions, but the endpoint is unavailable for "
                "space %s (%s); falling back to JSON-RPC.",
                space_key,
                e,
            )

    return _get_server_space_permissions_jsonrpc(confluence_client, space_key)


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
    add_prefix: bool = False,
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
            "No permissions found for space '%s'. This is very unlikely "
            "to be correct and is more likely caused by an access token with "
            "insufficient permissions. Make sure that the access token has Admin "
            "permissions for space '%s'",
            space_key,
            space_key,
        )

    # Prefix group IDs with source type if requested (for indexing path)
    if add_prefix and space_permissions.external_user_group_ids:
        prefixed_groups = {
            build_ext_group_name_for_onyx(g, DocumentSource.CONFLUENCE)
            for g in space_permissions.external_user_group_ids
        }
        return ExternalAccess(
            external_user_emails=space_permissions.external_user_emails,
            external_user_group_ids=prefixed_groups,
            is_public=space_permissions.is_public,
        )

    return space_permissions


def get_all_space_permissions(
    confluence_client: OnyxConfluence,
    is_cloud: bool,
    add_prefix: bool = False,
) -> dict[str, ExternalAccess]:
    """
    Get access permissions for all spaces in Confluence.

    add_prefix: When True, prefix group IDs with source type (for indexing path).
               When False (default), leave unprefixed (for permission sync path).
    """
    logger.debug("Getting space permissions")
    # Gets all the spaces in the Confluence instance
    all_space_keys = [
        key
        for space in confluence_client.retrieve_confluence_spaces(
            limit=REQUEST_PAGINATION_LIMIT,
        )
        if (key := space.get("key"))
    ]

    # Gets the permissions for each space
    logger.debug("Got %s spaces from confluence", len(all_space_keys))
    space_permissions_by_space_key: dict[str, ExternalAccess] = {}
    for space_key in all_space_keys:
        space_permissions = get_space_permission(
            confluence_client, space_key, is_cloud, add_prefix
        )

        # Stores the permissions for each space
        space_permissions_by_space_key[space_key] = space_permissions

    return space_permissions_by_space_key
