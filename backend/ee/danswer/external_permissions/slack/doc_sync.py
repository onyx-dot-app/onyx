from slack_sdk import WebClient
from sqlalchemy.orm import Session

from danswer.access.models import ExternalAccess
from danswer.connectors.factory import instantiate_connector
from danswer.connectors.interfaces import SlimConnector
from danswer.connectors.models import InputType
from danswer.connectors.slack.connector import get_channels
from danswer.connectors.slack.connector import make_paginated_slack_api_call_w_retries
from danswer.db.models import ConnectorCredentialPair
from danswer.db.users import batch_add_non_web_user_if_not_exists__no_commit
from danswer.utils.logger import setup_logger
from ee.danswer.db.document import upsert_document_external_perms__no_commit
from ee.danswer.external_permissions.slack.utils import fetch_user_id_to_email_map


logger = setup_logger()


def _get_slack_document_ids_and_channels(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> dict[str, list[str]]:
    # Get all document ids that need their permissions updated
    runnable_connector = instantiate_connector(
        db_session=db_session,
        source=cc_pair.connector.source,
        input_type=InputType.SLIM_RETRIEVAL,
        connector_specific_config=cc_pair.connector.connector_specific_config,
        credential=cc_pair.credential,
    )

    assert isinstance(runnable_connector, SlimConnector)

    channel_doc_map: dict[str, list[str]] = {}
    for doc_metadata_batch in runnable_connector.retrieve_all_slim_documents():
        for doc_metadata in doc_metadata_batch:
            if doc_metadata.perm_sync_data is None:
                continue
            channel_id = doc_metadata.perm_sync_data["channel_id"]
            if channel_id not in channel_doc_map:
                channel_doc_map[channel_id] = []
            channel_doc_map[channel_id].append(doc_metadata.id)

    return channel_doc_map


def _fetch_workspace_permissions(
    db_session: Session,
    user_id_to_email_map: dict[str, str],
) -> ExternalAccess:
    user_emails = set()
    for email in user_id_to_email_map.values():
        user_emails.add(email)
    batch_add_non_web_user_if_not_exists__no_commit(db_session, list(user_emails))
    return ExternalAccess(
        external_user_emails=user_emails,
        # No group<->document mapping for slack
        external_user_group_ids=set(),
        # No way to determine if slack is invite only without enterprise liscense
        is_public=False,
    )


def _fetch_channel_permissions(
    db_session: Session,
    slack_client: WebClient,
    workspace_permissions: ExternalAccess,
    user_id_to_email_map: dict[str, str],
) -> dict[str, ExternalAccess]:
    channel_permissions = {}
    public_channels = get_channels(
        client=slack_client,
        get_public=True,
        get_private=False,
    )
    public_channel_ids = [
        channel["id"] for channel in public_channels if "id" in channel
    ]
    for channel_id in public_channel_ids:
        channel_permissions[channel_id] = workspace_permissions

    private_channels = get_channels(
        client=slack_client,
        get_public=False,
        get_private=True,
    )
    private_channel_ids = [
        channel["id"] for channel in private_channels if "id" in channel
    ]

    for channel_id in private_channel_ids:
        # Collect all member ids for the channel pagination calls
        member_ids = []
        for result in make_paginated_slack_api_call_w_retries(
            slack_client.conversations_members,
            channel=channel_id,
        ):
            member_ids.extend(result.get("members", []))

        # Collect all member emails for the channel
        member_emails = set()
        for member_id in member_ids:
            member_email = user_id_to_email_map.get(member_id)

            if not member_email:
                # If the user is an external user, they wont get returned from the
                # conversations_members call so we need to make a separate call to users_info
                # and add them to the user_id_to_email_map
                member_info = slack_client.users_info(user=member_id)
                member_email = member_info["user"]["profile"].get("email")
                if not member_email:
                    # If no email is found, we skip the user
                    continue
                user_id_to_email_map[member_id] = member_email
                batch_add_non_web_user_if_not_exists__no_commit(
                    db_session, [member_email]
                )

            member_emails.add(member_email)

        channel_permissions[channel_id] = ExternalAccess(
            external_user_emails=member_emails,
            # No group<->document mapping for slack
            external_user_group_ids=set(),
            # No way to determine if slack is invite only without enterprise liscense
            is_public=False,
        )

    return channel_permissions


def slack_doc_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    """
    Adds the external permissions to the documents in postgres
    if the document doesn't already exists in postgres, we create
    it in postgres so that when it gets created later, the permissions are
    already populated
    """
    slack_client = WebClient(
        token=cc_pair.credential.credential_json["slack_bot_token"]
    )
    user_id_to_email_map = fetch_user_id_to_email_map(slack_client)
    channel_doc_map = _get_slack_document_ids_and_channels(
        db_session=db_session,
        cc_pair=cc_pair,
    )
    workspace_permissions = _fetch_workspace_permissions(
        db_session=db_session,
        user_id_to_email_map=user_id_to_email_map,
    )
    channel_permissions = _fetch_channel_permissions(
        db_session=db_session,
        slack_client=slack_client,
        workspace_permissions=workspace_permissions,
        user_id_to_email_map=user_id_to_email_map,
    )
    for channel_id, ext_access in channel_permissions.items():
        doc_ids = channel_doc_map.get(channel_id)
        if not doc_ids:
            # No documents found for channel the channel_id
            continue

        for doc_id in doc_ids:
            upsert_document_external_perms__no_commit(
                db_session=db_session,
                doc_id=doc_id,
                external_access=ext_access,
                source_type=cc_pair.connector.source,
            )
