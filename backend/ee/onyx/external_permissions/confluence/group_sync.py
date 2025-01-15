from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.confluence.constants import ALL_CONF_EMAILS_GROUP_NAME
from onyx.connectors.confluence.onyx_confluence import build_confluence_client
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.confluence.utils import get_user_email_from_username__server
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _build_group_member_email_map(
    confluence_client: OnyxConfluence,
) -> dict[str, set[str]]:
    group_member_emails: dict[str, set[str]] = {}
    for user_result in confluence_client.paginated_cql_user_retrieval():
        user = user_result.get("user", {})
        if not user:
            logger.warning(f"user result missing user field: {user_result}")
            continue
        email = user.get("email")
        if not email:
            # This field is only present in Confluence Server
            user_name = user.get("username")
            # If it is present, try to get the email using a Server-specific method
            if user_name:
                email = get_user_email_from_username__server(
                    confluence_client=confluence_client,
                    user_name=user_name,
                )
        if not email:
            # If we still don't have an email, skip this user
            logger.warning(f"user result missing email field: {user_result}")
            continue

        for group in confluence_client.paginated_groups_by_user_retrieval(user):
            # group name uniqueness is enforced by Confluence, so we can use it as a group ID
            group_id = group["name"]
            group_member_emails.setdefault(group_id, set()).add(email)

    return group_member_emails


def confluence_group_sync(
    cc_pair: ConnectorCredentialPair,
) -> list[ExternalUserGroup]:
    confluence_client = build_confluence_client(
        credentials=cc_pair.credential.credential_json,
        is_cloud=cc_pair.connector.connector_specific_config.get("is_cloud", False),
        wiki_base=cc_pair.connector.connector_specific_config["wiki_base"],
    )

    group_member_email_map = _build_group_member_email_map(
        confluence_client=confluence_client,
    )
    onyx_groups: list[ExternalUserGroup] = []
    all_found_emails = set()
    for group_id, group_member_emails in group_member_email_map.items():
        onyx_groups.append(
            ExternalUserGroup(
                id=group_id,
                user_emails=list(group_member_emails),
            )
        )
        all_found_emails.update(group_member_emails)

    # This is so that when we find a public confleunce server page, we can
    # give access to all users only in if they have an email in Confluence
    if cc_pair.connector.connector_specific_config.get("is_cloud", False):
        all_found_group = ExternalUserGroup(
            id=ALL_CONF_EMAILS_GROUP_NAME,
            user_emails=list(all_found_emails),
        )
        onyx_groups.append(all_found_group)

    return onyx_groups
