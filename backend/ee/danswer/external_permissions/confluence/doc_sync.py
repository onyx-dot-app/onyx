from typing import Any

from atlassian import Confluence  # type:ignore
from sqlalchemy.orm import Session

from danswer.access.models import ExternalAccess
from danswer.connectors.confluence.confluence_utils import (
    build_confluence_document_id,
)
from danswer.connectors.confluence.rate_limit_handler import (
    make_confluence_call_handle_rate_limit,
)
from danswer.db.models import ConnectorCredentialPair
from danswer.db.users import batch_add_non_web_user_if_not_exists__no_commit
from danswer.utils.logger import setup_logger
from ee.danswer.db.document import upsert_document_external_perms__no_commit
from ee.danswer.external_permissions.confluence.confluence_sync_utils import (
    build_confluence_client,
)


logger = setup_logger()

_REQUEST_PAGINATION_LIMIT = 100


def _get_space_permissions(
    db_session: Session,
    confluence_client: Confluence,
    space_id: str,
) -> ExternalAccess:
    get_space_permissions = make_confluence_call_handle_rate_limit(
        confluence_client.get_space_permissions
    )

    space_permissions = get_space_permissions(space_id).get("permissions", [])
    user_emails = set()
    # Confluence enforces that group names are unique
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
    batch_add_non_web_user_if_not_exists__no_commit(
        db_session=db_session, emails=list(user_emails)
    )
    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_names,
        is_public=is_externally_public,
    )


def _get_restrictions_for_page(
    db_session: Session,
    page: dict[str, Any],
    space_permissions: ExternalAccess,
) -> ExternalAccess:
    """
    WARNING: This function includes no pagination. So if a page is private within
    the space and has over 200 users or over 200 groups with explicitly read access,
    this function will leave out some users or groups.
    200 is a large amount so it is unlikely, but just be aware.
    """
    restrictions_json = page.get("restrictions", {})
    read_access_dict = restrictions_json.get("read", {}).get("restrictions", {})

    read_access_user_jsons = read_access_dict.get("user", {}).get("results", [])
    read_access_group_jsons = read_access_dict.get("group", {}).get("results", [])

    is_space_public = read_access_user_jsons == [] and read_access_group_jsons == []

    if not is_space_public:
        read_access_user_emails = [
            user["email"] for user in read_access_user_jsons if user.get("email")
        ]
        read_access_groups = [group["name"] for group in read_access_group_jsons]
        batch_add_non_web_user_if_not_exists__no_commit(
            db_session=db_session, emails=list(read_access_user_emails)
        )
        external_access = ExternalAccess(
            external_user_emails=set(read_access_user_emails),
            external_user_group_ids=set(read_access_groups),
            is_public=False,
        )
    else:
        external_access = space_permissions

    return external_access


def _fetch_attachment_document_ids_for_page_paginated(
    confluence_client: Confluence, page: dict[str, Any]
) -> list[str]:
    """
    Starts by just extracting the first page of attachments from
    the page. If all attachments are in the first page, then
    no calls to the api are made from this function.
    """
    get_attachments_from_content = make_confluence_call_handle_rate_limit(
        confluence_client.get_attachments_from_content
    )

    attachment_doc_ids = []
    attachments_dict = page["children"]["attachment"]
    start = 0

    while True:
        attachments_list = attachments_dict["results"]
        attachment_doc_ids.extend(
            [
                build_confluence_document_id(
                    base_url=confluence_client.url,
                    content_url=attachment["_links"]["download"],
                )
                for attachment in attachments_list
            ]
        )

        if "next" not in attachments_dict["_links"]:
            break

        start += len(attachments_list)
        attachments_dict = get_attachments_from_content(
            page_id=page["id"],
            start=start,
            limit=_REQUEST_PAGINATION_LIMIT,
        )

    return attachment_doc_ids


def _fetch_all_pages_paginated(
    confluence_client: Confluence,
    space_id: str,
) -> list[dict[str, Any]]:
    get_all_pages_from_space = make_confluence_call_handle_rate_limit(
        confluence_client.get_all_pages_from_space
    )

    # For each page, this fetches the page's attachments and restrictions.
    expansion_strings = [
        "children.attachment",
        "restrictions.read.restrictions.user",
        "restrictions.read.restrictions.group",
    ]
    expansion_string = ",".join(expansion_strings)

    all_pages = []
    start = 0
    while True:
        pages_dict = get_all_pages_from_space(
            space=space_id,
            start=start,
            limit=_REQUEST_PAGINATION_LIMIT,
            expand=expansion_string,
        )
        all_pages.extend(pages_dict)

        response_size = len(pages_dict)
        if response_size < _REQUEST_PAGINATION_LIMIT:
            break
        start += response_size

    return all_pages


def _fetch_all_page_restrictions_for_space(
    db_session: Session,
    confluence_client: Confluence,
    space_id: str,
    space_permissions: ExternalAccess,
) -> dict[str, ExternalAccess]:
    all_pages = _fetch_all_pages_paginated(
        confluence_client=confluence_client,
        space_id=space_id,
    )

    document_restrictions: dict[str, ExternalAccess] = {}
    for page in all_pages:
        """
        This assigns the same permissions to all attachments of a page and
        the page itself.
        This is because the attachments are stored in the same Confluence space as the page.
        WARNING: We create a dbDocument entry for all attachments, even though attachments
        may not be their own standalone documents. This is likely fine as we just upsert a
        document with just permissions.
        """
        attachment_document_ids = [
            build_confluence_document_id(
                base_url=confluence_client.url,
                content_url=page["_links"]["webui"],
            )
        ]
        attachment_document_ids.extend(
            _fetch_attachment_document_ids_for_page_paginated(
                confluence_client=confluence_client, page=page
            )
        )
        page_permissions = _get_restrictions_for_page(
            db_session=db_session,
            page=page,
            space_permissions=space_permissions,
        )
        for attachment_document_id in attachment_document_ids:
            document_restrictions[attachment_document_id] = page_permissions

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
    confluence_client = build_confluence_client(
        cc_pair.connector.connector_specific_config, cc_pair.credential.credential_json
    )
    space_permissions = _get_space_permissions(
        db_session=db_session,
        confluence_client=confluence_client,
        space_id=cc_pair.connector.connector_specific_config["space"],
    )
    fresh_doc_permissions = _fetch_all_page_restrictions_for_space(
        db_session=db_session,
        confluence_client=confluence_client,
        space_id=cc_pair.connector.connector_specific_config["space"],
        space_permissions=space_permissions,
    )
    for doc_id, ext_access in fresh_doc_permissions.items():
        upsert_document_external_perms__no_commit(
            db_session=db_session,
            doc_id=doc_id,
            external_access=ext_access,
            source_type=cc_pair.connector.source,
        )
