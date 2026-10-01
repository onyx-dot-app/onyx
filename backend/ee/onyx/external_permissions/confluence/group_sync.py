from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.confluence.constants import ALL_CONF_EMAILS_GROUP_NAME
from onyx.background.error_logging import emit_background_error
from onyx.configs.app_configs import CONFLUENCE_USE_ONYX_USERS_FOR_GROUP_SYNC
from onyx.connectors.confluence.source_operations import (
    ConfluenceSourceOperations,
    ConfluenceUserEmailVariant,
    build_probed_confluence_gateway,
    user_list_variant,
)
from onyx.connectors.credentials_provider import OnyxDBCredentialsProvider
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorCredentialPair
from onyx.db.users import get_all_users
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _build_group_member_email_map(
    source_operations: ConfluenceSourceOperations, cc_pair_id: int
) -> dict[str, set[str]]:
    group_member_emails: dict[str, set[str]] = {}
    for user in source_operations.list_users(
        variant=user_list_variant(source_operations)
    ):
        logger.info("Processing groups for user: %s", user)

        email = user.email
        if not email:
            # This field is only present in Confluence Server
            user_name = user.username
            # If it is present, try to get the email using a Server-specific method
            if user_name:
                email = source_operations.get_user_email(
                    variant=ConfluenceUserEmailVariant.USERNAME, user=user_name
                )
            else:
                logger.error("user result missing username field: %s", user)

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
        for group in source_operations.list_user_groups(user_id=user.user_id):
            # group name uniqueness is enforced by Confluence, so we can use it as a group ID
            group_id = group["name"]
            group_member_emails.setdefault(group_id, set()).add(email)
            all_users_groups.add(group_id)

        if not all_users_groups:
            msg = f"No groups found for user with email: {email}"
            emit_background_error(msg, cc_pair_id=cc_pair_id)
            logger.error(msg)
        else:
            logger.debug(
                "Found groups %s for user with email %s", all_users_groups, email
            )

    if not group_member_emails:
        msg = "No groups found for any users."
        emit_background_error(msg, cc_pair_id=cc_pair_id)
        logger.error(msg)

    return group_member_emails


def _build_group_member_email_map_from_onyx_users(
    source_operations: ConfluenceSourceOperations,
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
        logger.info("Processing groups for user with email: %s", email)
        try:
            user_name = _infer_username_from_email(email)
            response = source_operations.get_user_by_username(username=user_name)
            user_key = response.get("userKey")
            if not user_key:
                logger.error("User key not found for user with email %s", email)
                continue

            all_users_groups: set[str] = set()
            for group in source_operations.list_user_groups(user_id=user_key):
                # group name uniqueness is enforced by Confluence, so we can use it as a group ID
                group_id = group["name"]
                group_member_emails.setdefault(group_id, set()).add(email)
                all_users_groups.add(group_id)

            if not all_users_groups:
                msg = f"No groups found for user with email: {email}"
                logger.error(msg)
            else:
                logger.info(
                    "Found groups %s for user with email %s", all_users_groups, email
                )
        except Exception:
            logger.exception("Error getting user details for user with email %s", email)

    return group_member_emails


def _build_final_group_to_member_email_map(
    source_operations: ConfluenceSourceOperations,
    cc_pair_id: int,
    # if set, will infer confluence usernames from onyx users in addition to using the
    # confluence users API. This is a hacky workaround for the fact that the Confluence
    # users API is broken before Confluence Data Center 10.1.0.
    use_onyx_users: bool = CONFLUENCE_USE_ONYX_USERS_FOR_GROUP_SYNC,
) -> dict[str, set[str]]:
    group_to_member_email_map = _build_group_member_email_map(
        source_operations=source_operations,
        cc_pair_id=cc_pair_id,
    )
    group_to_member_email_map_from_onyx_users = (
        (
            _build_group_member_email_map_from_onyx_users(
                source_operations=source_operations,
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
    provider = OnyxDBCredentialsProvider(
        tenant_id, cc_pair.connector.source, cc_pair.credential_id
    )
    source_operations = build_probed_confluence_gateway(
        credentials_provider=provider,
        connector_specific_config=cc_pair.connector.connector_specific_config,
    )

    group_to_member_email_map = _build_final_group_to_member_email_map(
        source_operations, cc_pair.id
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
