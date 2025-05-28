"""
Rules defined here:
https://confluence.atlassian.com/conf85/check-who-can-view-a-page-1283360557.html
"""

from collections.abc import Generator
from typing import Any

from ee.onyx.configs.app_configs import CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC
from ee.onyx.external_permissions.confluence.constants import ALL_CONF_EMAILS_GROUP_NAME
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.confluence.onyx_confluence import (
    get_user_email_from_username__server,
)
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.credentials_provider import OnyxDBCredentialsProvider
from onyx.connectors.models import SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_VIEWSPACE_PERMISSION_TYPE = "VIEWSPACE"
_REQUEST_PAGINATION_LIMIT = 5000


def _get_server_space_permissions(
    confluence_client: OnyxConfluence, space_key: str
) -> ExternalAccess:
    space_permissions = confluence_client.get_all_space_permissions_server(
        space_key=space_key
    )

    viewspace_permissions = []
    for permission_category in space_permissions:
        if permission_category.get("type") == _VIEWSPACE_PERMISSION_TYPE:
            viewspace_permissions.extend(
                permission_category.get("spacePermissions", [])
            )

    is_public = False
    user_names = set()
    group_names = set()
    for permission in viewspace_permissions:
        user_name = permission.get("userName")
        if user_name:
            user_names.add(user_name)
        group_name = permission.get("groupName")
        if group_name:
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


def _get_space_permissions(
    confluence_client: OnyxConfluence,
    is_cloud: bool,
) -> dict[str, ExternalAccess]:
    logger.debug("Getting space permissions")
    # Gets all the spaces in the Confluence instance
    all_space_keys = []
    start = 0
    while True:
        spaces_batch = confluence_client.get_all_spaces(
            start=start, limit=_REQUEST_PAGINATION_LIMIT
        )
        for space in spaces_batch.get("results", []):
            all_space_keys.append(space.get("key"))

        if len(spaces_batch.get("results", [])) < _REQUEST_PAGINATION_LIMIT:
            break

        start += len(spaces_batch.get("results", []))

    # Gets the permissions for each space
    logger.debug(f"Got {len(all_space_keys)} spaces from confluence")
    space_permissions_by_space_key: dict[str, ExternalAccess] = {}
    for space_key in all_space_keys:
        if is_cloud:
            space_permissions = _get_cloud_space_permissions(
                confluence_client=confluence_client, space_key=space_key
            )
        else:
            space_permissions = _get_server_space_permissions(
                confluence_client=confluence_client, space_key=space_key
            )

        # Stores the permissions for each space
        space_permissions_by_space_key[space_key] = space_permissions
        if (
            not space_permissions.is_public
            and not space_permissions.external_user_emails
            and not space_permissions.external_user_group_ids
        ):
            logger.warning(
                f"No permissions found for space '{space_key}'. This is very unlikely"
                "to be correct and is more likely caused by an access token with"
                "insufficient permissions. Make sure that the access token has Admin"
                f"permissions for space '{space_key}'"
            )

    return space_permissions_by_space_key


def _extract_read_access_restrictions(
    confluence_client: OnyxConfluence, restrictions: dict[str, Any]
) -> tuple[set[str], set[str], bool]:
    """
    Converts a page's restrictions dict into an ExternalAccess object.
    If there are no restrictions, then return None
    """
    read_access = restrictions.get("read", {})
    read_access_restrictions = read_access.get("restrictions", {})

    # Extract the users with read access
    read_access_user = read_access_restrictions.get("user", {})
    read_access_user_jsons = read_access_user.get("results", [])
    # any items found means that there is a restriction
    found_any_restriction = bool(read_access_user_jsons)

    read_access_user_emails = []
    for user in read_access_user_jsons:
        # If the user has an email, then add it to the list
        if user.get("email"):
            read_access_user_emails.append(user["email"])
        # If the user has a username and not an email, then get the email from Confluence
        elif user.get("username"):
            email = get_user_email_from_username__server(
                confluence_client=confluence_client, user_name=user["username"]
            )
            if email:
                read_access_user_emails.append(email)
            else:
                logger.warning(
                    f"Email for user {user['username']} not found in Confluence"
                )
        else:
            if user.get("email") is not None:
                logger.warning(f"Cant find email for user {user.get('displayName')}")
                logger.warning(
                    "This user needs to make their email accessible in Confluence Settings"
                )

            logger.warning(f"no user email or username for {user}")

    # Extract the groups with read access
    read_access_group = read_access_restrictions.get("group", {})
    read_access_group_jsons = read_access_group.get("results", [])
    # any items found means that there is a restriction
    found_any_restriction |= bool(read_access_group_jsons)
    read_access_group_names = [
        group["name"] for group in read_access_group_jsons if group.get("name")
    ]

    return (
        set(read_access_user_emails),
        set(read_access_group_names),
        found_any_restriction,
    )


def _get_all_page_restrictions(
    confluence_client: OnyxConfluence,
    perm_sync_data: dict[str, Any],
) -> ExternalAccess | None:
    """
    This function gets the restrictions for a page. In Confluence, a child can have
    at MOST the same level accessibility as its immediate parent.

    If no restrictions are found anywhere, then return None, indicating that the page
    should inherit the space's restrictions.
    """
    found_user_emails: set[str] = set()
    found_group_names: set[str] = set()

    # NOTE: need the found_any_restriction, since we can find restrictions
    # but not be able to extract any user emails or group names
    # in this case, we should just give no access
    found_user_emails, found_group_names, found_any_page_level_restriction = (
        _extract_read_access_restrictions(
            confluence_client=confluence_client,
            restrictions=perm_sync_data.get("restrictions", {}),
        )
    )
    # if there are individual page-level restrictions, then this is the accurate
    # restriction for the page. You cannot both have page-level restrictions AND
    # inherit restrictions from the parent.
    if found_any_page_level_restriction:
        return ExternalAccess(
            external_user_emails=found_user_emails,
            external_user_group_ids=found_group_names,
            is_public=False,
        )

    ancestors: list[dict[str, Any]] = perm_sync_data.get("ancestors", [])
    # ancestors seem to be in order from root to immediate parent
    # https://community.atlassian.com/forums/Confluence-questions/Order-of-ancestors-in-REST-API-response-Confluence-Server-amp/qaq-p/2385981
    # we want the restrictions from the immediate parent to take precedence, so we should
    # reverse the list
    for ancestor in reversed(ancestors):
        (
            ancestor_user_emails,
            ancestor_group_names,
            found_any_restrictions_in_ancestor,
        ) = _extract_read_access_restrictions(
            confluence_client=confluence_client,
            restrictions=ancestor.get("restrictions", {}),
        )
        if found_any_restrictions_in_ancestor:
            # if inheriting restrictions from the parent, then the first one we run into
            # should be applied (the reason why we'd traverse more than one ancestor is if
            # the ancestor also is in "inherit" mode.)
            logger.info(
                f"Found user restrictions {ancestor_user_emails} and group restrictions {ancestor_group_names}"
                f"for document {perm_sync_data.get('id')} based on ancestor {ancestor}"
            )
            return ExternalAccess(
                external_user_emails=ancestor_user_emails,
                external_user_group_ids=ancestor_group_names,
                is_public=False,
            )

    # we didn't find any restrictions, so the page inherits the space's restrictions
    return None


def _fetch_all_page_restrictions(
    confluence_client: OnyxConfluence,
    slim_docs: list[SlimDocument],
    space_permissions_by_space_key: dict[str, ExternalAccess],
    is_cloud: bool,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[DocExternalAccess, None, None]:
    """
    For all pages, if a page has restrictions, then use those restrictions.
    Otherwise, use the space's restrictions.
    """
    for slim_doc in slim_docs:
        if callback:
            if callback.should_stop():
                raise RuntimeError("confluence_doc_sync: Stop signal detected")

            callback.progress("confluence_doc_sync:fetch_all_page_restrictions", 1)

        if slim_doc.perm_sync_data is None:
            raise ValueError(
                f"No permission sync data found for document {slim_doc.id}"
            )

        if restrictions := _get_all_page_restrictions(
            confluence_client=confluence_client,
            perm_sync_data=slim_doc.perm_sync_data,
        ):
            logger.info(f"Found restrictions {restrictions} for document {slim_doc.id}")
            yield DocExternalAccess(
                doc_id=slim_doc.id,
                external_access=restrictions,
            )
            # If there are restrictions, then we don't need to use the space's restrictions
            continue

        space_key = slim_doc.perm_sync_data.get("space_key")
        if not (space_permissions := space_permissions_by_space_key.get(space_key)):
            logger.warning(
                f"Individually fetching space permissions for space {space_key}. This is "
                "unexpected. It means the permissions were not able to fetched initially."
            )
            try:
                # If the space permissions are not in the cache, then fetch them
                if is_cloud:
                    retrieved_space_permissions = _get_cloud_space_permissions(
                        confluence_client=confluence_client, space_key=space_key
                    )
                else:
                    retrieved_space_permissions = _get_server_space_permissions(
                        confluence_client=confluence_client, space_key=space_key
                    )
                space_permissions_by_space_key[space_key] = retrieved_space_permissions
                space_permissions = retrieved_space_permissions
            except Exception as e:
                logger.warning(
                    f"Error fetching space permissions for space {space_key}: {e}"
                )

        if not space_permissions:
            logger.warning(
                f"No permissions found for document {slim_doc.id} in space {space_key}"
            )
            # be safe, if we can't get the permissions then make the document inaccessible
            yield DocExternalAccess(
                doc_id=slim_doc.id,
                external_access=ExternalAccess(
                    external_user_emails=set(),
                    external_user_group_ids=set(),
                    is_public=False,
                ),
            )
            continue

        # If there are no restrictions, then use the space's restrictions
        yield DocExternalAccess(
            doc_id=slim_doc.id,
            external_access=space_permissions,
        )
        if (
            not space_permissions.is_public
            and not space_permissions.external_user_emails
            and not space_permissions.external_user_group_ids
        ):
            logger.warning(
                f"Permissions are empty for document: {slim_doc.id}\n"
                "This means space permissions may be wrong for"
                f" Space key: {space_key}"
            )

    logger.info("Finished fetching all page restrictions")


def confluence_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[DocExternalAccess, None, None]:
    """
    Fetches document permissions from Confluence and yields DocExternalAccess objects.
    Compares fetched documents against existing documents in the DB for the connector.
    If a document exists in the DB but not in the Confluence fetch, it's marked as restricted.
    """
    logger.info(f"Starting confluence doc sync for CC Pair ID: {cc_pair.id}")
    confluence_connector = ConfluenceConnector(
        **cc_pair.connector.connector_specific_config
    )

    provider = OnyxDBCredentialsProvider(
        get_current_tenant_id(), "confluence", cc_pair.credential_id
    )
    confluence_connector.set_credentials_provider(provider)

    is_cloud = cc_pair.connector.connector_specific_config.get("is_cloud", False)

    space_permissions_by_space_key = _get_space_permissions(
        confluence_client=confluence_connector.confluence_client,
        is_cloud=is_cloud,
    )
    logger.info("Space permissions by space key:")
    for space_key, space_permissions in space_permissions_by_space_key.items():
        logger.info(f"Space key: {space_key}, Permissions: {space_permissions}")

    slim_docs: list[SlimDocument] = []
    logger.info("Fetching all slim documents from confluence")
    for doc_batch in confluence_connector.retrieve_all_slim_documents(
        callback=callback
    ):
        logger.info(f"Got {len(doc_batch)} slim documents from confluence")
        if callback:
            if callback.should_stop():
                raise RuntimeError("confluence_doc_sync: Stop signal detected")

            callback.progress("confluence_doc_sync", 1)

        slim_docs.extend(doc_batch)

    # Find documents that are no longer accessible in Confluence
    logger.info(f"Querying existing document IDs for CC Pair ID: {cc_pair.id}")
    existing_doc_ids = fetch_all_existing_docs_fn()

    # Find missing doc IDs
    fetched_doc_ids = {doc.id for doc in slim_docs}
    missing_doc_ids = set(existing_doc_ids) - fetched_doc_ids

    # Yield access removal for missing docs. Better to be safe.
    if missing_doc_ids:
        logger.warning(
            f"Found {len(missing_doc_ids)} documents that are in the DB but "
            "not present in Confluence fetch. Making them inaccessible."
        )
        for missing_id in missing_doc_ids:
            logger.warning(f"Removing access for document ID: {missing_id}")
            yield DocExternalAccess(
                doc_id=missing_id,
                external_access=ExternalAccess(
                    external_user_emails=set(),
                    external_user_group_ids=set(),
                    is_public=False,
                ),
            )

    logger.info("Fetching all page restrictions for fetched documents")
    yield from _fetch_all_page_restrictions(
        confluence_client=confluence_connector.confluence_client,
        slim_docs=slim_docs,
        space_permissions_by_space_key=space_permissions_by_space_key,
        is_cloud=is_cloud,
        callback=callback,
    )

    logger.info("Finished confluence doc sync")
