from collections.abc import Generator

from slack_sdk import WebClient

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsIdsFunction
from ee.onyx.external_permissions.slack.channel_access import get_channel_access
from ee.onyx.external_permissions.slack.utils import fetch_team_user_emails
from ee.onyx.external_permissions.slack.utils import fetch_user_id_to_email_map
from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.connectors.credentials_provider import OnyxDBCredentialsProvider
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import HierarchyNode
from onyx.connectors.slack.connector import get_channels
from onyx.connectors.slack.connector import get_channels_across_teams
from onyx.connectors.slack.connector import list_grid_team_ids
from onyx.connectors.slack.connector import make_paginated_slack_api_call
from onyx.connectors.slack.connector import SlackConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


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
        # No way to determine if slack is invite only without enterprise license
        is_public=False,
    )


def _fetch_channel_permissions(
    slack_client: WebClient,
    workspace_permissions: ExternalAccess,  # noqa: ARG001
    user_id_to_email_map: dict[str, str],
    team_ids: list[str] | None = None,
    team_id_to_user_emails: dict[str, set[str]] | None = None,
) -> dict[str, ExternalAccess]:
    channel_permissions = {}
    if team_ids:
        public_channels = get_channels_across_teams(
            client=slack_client,
            team_ids=team_ids,
            get_public=True,
            get_private=False,
        )
        private_channels = get_channels_across_teams(
            client=slack_client,
            team_ids=team_ids,
            get_public=False,
            get_private=True,
        )
    else:
        public_channels = get_channels(
            client=slack_client,
            get_public=True,
            get_private=False,
        )
        private_channels = get_channels(
            client=slack_client,
            get_public=False,
            get_private=True,
        )
    for channel in public_channels:
        channel_id = channel.get("id")
        if not channel_id:
            continue
        if team_id_to_user_emails:
            channel_permissions[channel_id] = get_channel_access(
                client=slack_client,
                channel=channel,
                user_cache={},
                team_id_to_user_emails=team_id_to_user_emails,
            )
        # Non-Grid public channels keep their ingest-time is_public=True; no
        # override entry so `_get_slack_document_access` falls back to the slim
        # doc's original access.

    private_channel_ids = [
        channel["id"] for channel in private_channels if "id" in channel
    ]

    for channel_id in private_channel_ids:
        # Collect all member ids for the channel pagination calls
        member_ids = []
        for result in make_paginated_slack_api_call(
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
            # No way to determine if slack is invite only without enterprise license
            is_public=False,
        )

    return channel_permissions


def _get_slack_document_access(
    slack_connector: SlackConnector,
    channel_permissions: dict[str, ExternalAccess],
    callback: IndexingHeartbeatInterface | None,
    indexing_start: SecondsSinceUnixEpoch | None = None,
) -> Generator[DocExternalAccess, None, None]:
    slim_doc_generator = slack_connector.retrieve_all_slim_docs_perm_sync(
        callback=callback,
        start=indexing_start,
    )

    for doc_metadata_batch in slim_doc_generator:
        for doc_metadata in doc_metadata_batch:
            if isinstance(doc_metadata, HierarchyNode):
                # TODO: handle hierarchynodes during sync
                continue
            external_access = doc_metadata.external_access
            if external_access is None:
                raise ValueError(
                    f"No external access for document {doc_metadata.id}. "
                    "Please check to make sure that your Slack bot token has the "
                    "`channels:read` scope"
                )
            channel_id = getattr(doc_metadata, "parent_hierarchy_raw_node_id", None)
            if channel_id is not None:
                override_access = channel_permissions.get(channel_id)
                if override_access is not None:
                    external_access = override_access

            yield DocExternalAccess(
                external_access=external_access,
                doc_id=doc_metadata.id,
            )

        if callback:
            if callback.should_stop():
                raise RuntimeError("_get_slack_document_access: Stop signal detected")

            callback.progress("_get_slack_document_access", 1)


def slack_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,  # noqa: ARG001
    callback: IndexingHeartbeatInterface | None,
) -> Generator[DocExternalAccess, None, None]:
    """
    Adds the external permissions to the documents in postgres
    if the document doesn't already exists in postgres, we create
    it in postgres so that when it gets created later, the permissions are
    already populated
    """
    # Use credentials provider instead of directly loading credentials

    tenant_id = get_current_tenant_id()
    provider = OnyxDBCredentialsProvider(tenant_id, "slack", cc_pair.credential.id)
    r = get_redis_client(tenant_id=tenant_id)
    credential_json = (
        cc_pair.credential.credential_json.get_value(apply_mask=False)
        if cc_pair.credential.credential_json
        else {}
    )
    slack_client = SlackConnector.make_slack_web_client(
        provider.get_provider_key(),
        credential_json["slack_bot_token"],
        SlackConnector.MAX_RETRIES,
        r,
    )

    grid_team_ids: list[str] | None = None
    try:
        auth_response = slack_client.auth_test()
        if auth_response.get("enterprise_id"):
            grid_team_ids = list_grid_team_ids(slack_client)
    except Exception as e:
        logger.warning("Slack Grid detection during perm sync failed: %s", e)

    team_id_to_user_emails: dict[str, set[str]] | None = None
    if grid_team_ids:
        try:
            team_id_to_user_emails = fetch_team_user_emails(slack_client, grid_team_ids)
        except Exception as e:
            # Without per-team users, Grid public-channel scoping degrades to
            # is_public via the empty-union fallback. Keep perm-sync running.
            logger.warning("fetch_team_user_emails failed on Grid org: %s", e)
            team_id_to_user_emails = None
        user_id_to_email_map = fetch_user_id_to_email_map(
            slack_client, team_ids=grid_team_ids
        )
    else:
        user_id_to_email_map = fetch_user_id_to_email_map(slack_client)
    if not user_id_to_email_map:
        raise ValueError(
            "No user id to email map found. Please check to make sure that your Slack bot token has the `users:read.email` scope"
        )

    workspace_permissions = _fetch_workspace_permissions(
        user_id_to_email_map=user_id_to_email_map,
    )
    channel_permissions = _fetch_channel_permissions(
        slack_client=slack_client,
        workspace_permissions=workspace_permissions,
        user_id_to_email_map=user_id_to_email_map,
        team_ids=grid_team_ids,
        team_id_to_user_emails=team_id_to_user_emails,
    )

    slack_connector = SlackConnector(**cc_pair.connector.connector_specific_config)
    slack_connector.set_credentials_provider(provider)
    indexing_start_ts: SecondsSinceUnixEpoch | None = (
        cc_pair.connector.indexing_start.timestamp()
        if cc_pair.connector.indexing_start is not None
        else None
    )

    yield from _get_slack_document_access(
        slack_connector=slack_connector,
        channel_permissions=channel_permissions,
        callback=callback,
        indexing_start=indexing_start_ts,
    )
