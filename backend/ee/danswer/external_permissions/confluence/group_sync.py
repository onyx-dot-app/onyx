
from danswer.connectors.confluence.onyx_confluence import build_confluence_client
from danswer.connectors.confluence.onyx_confluence import OnyxConfluence
from danswer.connectors.confluence.utils import get_user_email_from_username__server
from danswer.db.models import ConnectorCredentialPair
from danswer.utils.logger import setup_logger
from ee.danswer.db.external_perm import ExternalUserGroup


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
    danswer_groups: list[ExternalUserGroup] = []
    for group_id, group_member_emails in group_member_email_map.items():
        danswer_groups.append(
            ExternalUserGroup(
                id=group_id,
                user_emails=list(group_member_emails),
            )
        )

    return danswer_groups
