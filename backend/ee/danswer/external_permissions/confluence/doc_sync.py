"""
Rules defined here:
https://confluence.atlassian.com/conf85/check-who-can-view-a-page-1283360557.html
"""
from typing import Any

from sqlalchemy.orm import Session

from danswer.access.models import ExternalAccess
from danswer.connectors.confluence.connector import ConfluenceConnector
from danswer.connectors.confluence.onyx_confluence import OnyxConfluence
from danswer.connectors.confluence.utils import get_user_email_from_username__server
from danswer.connectors.models import SlimDocument
from danswer.db.models import ConnectorCredentialPair
from danswer.db.users import batch_add_non_web_user_if_not_exists__no_commit
from danswer.utils.logger import setup_logger
from ee.danswer.db.document import upsert_document_external_perms__no_commit

logger = setup_logger()

_VIEWSPACE_PERMISSION_TYPE = "VIEWSPACE"
_REQUEST_PAGINATION_LIMIT = 100


def _get_server_space_permissions(
    confluence_client: OnyxConfluence, space_key: str
) -> ExternalAccess:
    space_permissions = confluence_client.get_space_permissions(space_key=space_key)

    viewspace_permissions = []
    for permission_category in space_permissions:
        if permission_category.get("type") == _VIEWSPACE_PERMISSION_TYPE:
            viewspace_permissions.extend(
                permission_category.get("spacePermissions", [])
            )

    user_names = set()
    group_names = set()
    for permission in viewspace_permissions:
        if user_name := permission.get("userName"):
            user_names.add(user_name)
        if group_name := permission.get("groupName"):
            group_names.add(group_name)

    user_emails = set()
    for user_name in user_names:
        user_email = get_user_email_from_username__server(confluence_client, user_name)
        if user_email:
            user_emails.add(user_email)
        else:
            logger.warning(f"Email for user {user_name} not found in Confluence")

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_names,
        # TODO: Check if the space is publicly accessible
        # Currently, we assume the space is not public
        # We need to check if anonymous access is turned on for the site and space
        # This information is paywalled so it remains unimplemented
        is_public=False,
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

    return space_permissions_by_space_key


def _extract_read_access_restrictions(
    confluence_client: OnyxConfluence, restrictions: dict[str, Any]
) -> ExternalAccess | None:
    """
    Converts a page's restrictions dict into an ExternalAccess object.
    If there are no restrictions, then return None
    """
    read_access = restrictions.get("read", {})
    read_access_restrictions = read_access.get("restrictions", {})

    # Extract the users with read access
    read_access_user = read_access_restrictions.get("user", {})
    read_access_user_jsons = read_access_user.get("results", [])
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
            logger.warning(f"User {user} does not have an email or username")

    # Extract the groups with read access
    read_access_group = read_access_restrictions.get("group", {})
    read_access_group_jsons = read_access_group.get("results", [])
    read_access_group_names = [
        group["name"] for group in read_access_group_jsons if group.get("name")
    ]

    # If there are no restrictions found, then the page
    # inherits the space's restrictions so return None
    is_space_public = read_access_user_emails == [] and read_access_group_names == []
    if is_space_public:
        return None

    return ExternalAccess(
        external_user_emails=set(read_access_user_emails),
        external_user_group_ids=set(read_access_group_names),
        # there is no way for a page to be individually public if the space isn't public
        is_public=False,
    )


def _fetch_all_page_restrictions_for_space(
    confluence_client: OnyxConfluence,
    slim_docs: list[SlimDocument],
    space_permissions_by_space_key: dict[str, ExternalAccess],
) -> dict[str, ExternalAccess]:
    """
    For all pages, if a page has restrictions, then use those restrictions.
    Otherwise, use the space's restrictions.
    """
    document_restrictions: dict[str, ExternalAccess] = {}

    for slim_doc in slim_docs:
        if slim_doc.perm_sync_data is None:
            raise ValueError(
                f"No permission sync data found for document {slim_doc.id}"
            )
        restrictions = _extract_read_access_restrictions(
            confluence_client=confluence_client,
            restrictions=slim_doc.perm_sync_data.get("restrictions", {}),
        )
        if restrictions:
            document_restrictions[slim_doc.id] = restrictions
        else:
            space_key = slim_doc.perm_sync_data.get("space_key")
            if space_permissions := space_permissions_by_space_key.get(space_key):
                document_restrictions[slim_doc.id] = space_permissions
            else:
                logger.warning(f"No permissions found for document {slim_doc.id}")

    return document_restrictions


def confluence_doc_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    """
    Adds the external permissions to the documents in postgres
    if the document doesn't already exists in postgres, we create
    it in postgres so that when it gets created later, the permissions are
    already populated
    """
    confluence_connector = ConfluenceConnector(
        **cc_pair.connector.connector_specific_config
    )
    confluence_connector.load_credentials(cc_pair.credential.credential_json)
    if confluence_connector.confluence_client is None:
        raise ValueError("Failed to load credentials")
    confluence_client = confluence_connector.confluence_client

    is_cloud = cc_pair.connector.connector_specific_config.get("is_cloud", False)

    space_permissions_by_space_key = _get_space_permissions(
        confluence_client=confluence_client,
        is_cloud=is_cloud,
    )

    slim_docs = []
    for doc_batch in confluence_connector.retrieve_all_slim_documents():
        slim_docs.extend(doc_batch)

    permissions_by_doc_id = _fetch_all_page_restrictions_for_space(
        confluence_client=confluence_client,
        slim_docs=slim_docs,
        space_permissions_by_space_key=space_permissions_by_space_key,
    )

    all_emails = set()
    for doc_id, page_specific_access in permissions_by_doc_id.items():
        upsert_document_external_perms__no_commit(
            db_session=db_session,
            doc_id=doc_id,
            external_access=page_specific_access,
            source_type=cc_pair.connector.source,
        )
        all_emails.update(page_specific_access.external_user_emails)

    batch_add_non_web_user_if_not_exists__no_commit(db_session, list(all_emails))
