from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.confluence.constants import ALL_CONF_EMAILS_GROUP_NAME
from onyx.background.error_logging import emit_background_error
from onyx.configs.app_configs import CONFLUENCE_USE_ONYX_USERS_FOR_GROUP_SYNC
from onyx.connectors.confluence.onyx_confluence import (
    get_user_email_from_username__server,
)
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.credentials_provider import OnyxDBCredentialsProvider
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorCredentialPair
from onyx.db.users import get_all_users
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _build_group_member_email_map(
    confluence_client: OnyxConfluence, cc_pair_id: int
) -> dict[str, set[str]]:
    group_member_emails: dict[str, set[str]] = {}
    for user in confluence_client.paginated_cql_user_retrieval():
        logger.info(f"Processing groups for user: {user}")

        email = user.email
        if not email:
            # This field is only present in Confluence Server
            user_name = user.username
            # If it is present, try to get the email using a Server-specific method
            if user_name:
                email = get_user_email_from_username__server(
                    confluence_client=confluence_client,
                    user_name=user_name,
                )
            else:
                logger.error(f"user result missing username field: {user}")

        if not email:
            # If we still don't have an email, skip this user
            msg = f"user result missing email field: {user}"
            if user.type == "app":
                logger.warning(msg)
            else:
                emit_background_error(msg, cc_pair_id=cc_pair_id)
                logger.error(msg)
            continue

        all_users_groups: set[str] = set()
        for group in confluence_client.paginated_groups_by_user_retrieval(user.user_id):
            # group name uniqueness is enforced by Confluence, so we can use it as a group ID
            group_id = group["name"]
            group_member_emails.setdefault(group_id, set()).add(email)
            all_users_groups.add(group_id)

        if not all_users_groups:
            msg = f"No groups found for user with email: {email}"
            emit_background_error(msg, cc_pair_id=cc_pair_id)
            logger.error(msg)
        else:
            logger.debug(f"Found groups {all_users_groups} for user with email {email}")

    if not group_member_emails:
        msg = "No groups found for any users."
        emit_background_error(msg, cc_pair_id=cc_pair_id)
        logger.error(msg)

    return group_member_emails


def _build_group_member_email_map_from_onyx_users(
    confluence_client: OnyxConfluence,
) -> dict[str, set[str]]:
    """Hacky, but it's the only way to do this as long as the
    Confluence APIs are broken.

    This is fixed in Confluence Data Center 10.1.0, so first choice
    is to tell users to upgrade to 10.1.0.
    https://jira.atlassian.com/browse/CONFSERVER-95999
    """
    with get_session_with_current_tenant() as db_session:
        # don't include external since they are handled by the "through confluence"
        # user fetching mechanism
        user_emails = [
            user.email for user in get_all_users(db_session, include_external=False)
        ]

    def _infer_username_from_email(email: str) -> str:
        return email.split("@")[0]

    group_member_emails: dict[str, set[str]] = {}
    for email in user_emails:
        logger.info(f"Processing groups for user with email: {email}")
        try:
            user_name = _infer_username_from_email(email)
            response = confluence_client.get_user_details_by_username(user_name)
            user_key = response.get("userKey")
            if not user_key:
                logger.error(f"User key not found for user with email {email}")
                continue

            all_users_groups: set[str] = set()
            for group in confluence_client.paginated_groups_by_user_retrieval(user_key):
                # group name uniqueness is enforced by Confluence, so we can use it as a group ID
                group_id = group["name"]
                group_member_emails.setdefault(group_id, set()).add(email)
                all_users_groups.add(group_id)

            if not all_users_groups:
                msg = f"No groups found for user with email: {email}"
                logger.error(msg)
            else:
                logger.info(
                    f"Found groups {all_users_groups} for user with email {email}"
                )
        except Exception:
            logger.exception(f"Error getting user details for user with email {email}")

    return group_member_emails


def _build_final_group_to_member_email_map(
    confluence_client: OnyxConfluence,
    cc_pair_id: int,
    # if set, will infer confluence usernames from onyx users in addition to using the
    # confluence users API. This is a hacky workaround for the fact that the Confluence
    # users API is broken before Confluence Data Center 10.1.0.
    use_onyx_users: bool = CONFLUENCE_USE_ONYX_USERS_FOR_GROUP_SYNC,
) -> dict[str, set[str]]:
    group_to_member_email_map = _build_group_member_email_map(
        confluence_client=confluence_client,
        cc_pair_id=cc_pair_id,
    )
    group_to_member_email_map_from_onyx_users = (
        (
            _build_group_member_email_map_from_onyx_users(
                confluence_client=confluence_client,
            )
        )
        if use_onyx_users
        else {}
    )

    all_group_ids = set(group_to_member_email_map.keys()) | set(
        group_to_member_email_map_from_onyx_users.keys()
    )
    final_group_to_member_email_map = {}
    for group_id in all_group_ids:
        group_member_emails = group_to_member_email_map.get(
            group_id, set()
        ) | group_to_member_email_map_from_onyx_users.get(group_id, set())
        final_group_to_member_email_map[group_id] = group_member_emails

    return final_group_to_member_email_map


def confluence_group_sync(
    tenant_id: str,
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    provider = OnyxDBCredentialsProvider(tenant_id, "confluence", cc_pair.credential_id)
    is_cloud = cc_pair.connector.connector_specific_config.get("is_cloud", False)
    wiki_base: str = cc_pair.connector.connector_specific_config["wiki_base"]
    url = wiki_base.rstrip("/")

    probe_kwargs = {
        "max_backoff_retries": 6,
        "max_backoff_seconds": 10,
    }

    final_kwargs = {
        "max_backoff_retries": 10,
        "max_backoff_seconds": 60,
    }

    confluence_client = OnyxConfluence(is_cloud, url, provider)
    confluence_client._probe_connection(**probe_kwargs)
    confluence_client._initialize_connection(**final_kwargs)

    group_to_member_email_map = _build_final_group_to_member_email_map(
        confluence_client, cc_pair.id
    )

    all_found_emails = set()
    for group_id, group_member_emails in group_to_member_email_map.items():
        yield (
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
        yield all_found_group
