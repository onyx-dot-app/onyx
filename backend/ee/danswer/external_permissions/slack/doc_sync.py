from slack_sdk import WebClient

from danswer.access.models import DocExternalAccess
from danswer.access.models import ExternalAccess
from danswer.connectors.slack.connector import get_channels
from danswer.connectors.slack.connector import make_paginated_slack_api_call_w_retries
from danswer.connectors.slack.connector import SlackPollConnector
from danswer.db.models import ConnectorCredentialPair
from danswer.utils.logger import setup_logger
from ee.danswer.external_permissions.slack.utils import fetch_user_id_to_email_map


logger = setup_logger()


def _get_slack_document_ids_and_channels(
    cc_pair: ConnectorCredentialPair,
) -> dict[str, list[str]]:
    slack_connector = SlackPollConnector(**cc_pair.connector.connector_specific_config)
    slack_connector.load_credentials(cc_pair.credential.credential_json)

    slim_doc_generator = slack_connector.retrieve_all_slim_documents()

    channel_doc_map: dict[str, list[str]] = {}
    for doc_metadata_batch in slim_doc_generator:
        for doc_metadata in doc_metadata_batch:
            if doc_metadata.perm_sync_data is None:
                continue
            channel_id = doc_metadata.perm_sync_data["channel_id"]
            if channel_id not in channel_doc_map:
                channel_doc_map[channel_id] = []
            channel_doc_map[channel_id].append(doc_metadata.id)

    return channel_doc_map


def _fetch_workspace_permissions(
    user_id_to_email_map: dict[str, str],
) -> ExternalAccess:
    user_emails = set()
    for email in user_id_to_email_map.values():
        user_emails.add(email)
    return ExternalAccess(
        external_user_emails=user_emails,
        # No group<->document mapping for slack
        external_user_group_ids=set(),
        # No way to determine if slack is invite only without enterprise liscense
        is_public=False,
    )


def _fetch_channel_permissions(
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
    cc_pair: ConnectorCredentialPair,
) -> list[DocExternalAccess]:
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
        cc_pair=cc_pair,
    )
    workspace_permissions = _fetch_workspace_permissions(
        user_id_to_email_map=user_id_to_email_map,
    )
    channel_permissions = _fetch_channel_permissions(
        slack_client=slack_client,
        workspace_permissions=workspace_permissions,
        user_id_to_email_map=user_id_to_email_map,
    )

    document_external_accesses = []
    for channel_id, ext_access in channel_permissions.items():
        doc_ids = channel_doc_map.get(channel_id)
        if not doc_ids:
            # No documents found for channel the channel_id
            continue

        for doc_id in doc_ids:
            document_external_accesses.append(
                DocExternalAccess(
                    external_access=ext_access,
                    doc_id=doc_id,
                )
            )
    return document_external_accesses
