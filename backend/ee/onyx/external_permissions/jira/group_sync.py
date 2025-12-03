from collections.abc import Generator

from jira import JIRA

from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.connectors.jira.utils import build_jira_client
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_jira_group_members_email(
    jira_client: JIRA,
    group_name: str,
) -> list[str]:
    """Get all member emails for a Jira group.

    Filters out app accounts (bots, integrations) and only returns real user emails.
    """
    emails: list[str] = []

    try:
        # group_members returns an OrderedDict of account_id -> member_info
        members = jira_client.group_members(group=group_name)

        if not members:
            logger.warning(f"No members found for group {group_name}")
            return emails

        for account_id, member_info in members.items():
            # member_info is a dict with keys like 'fullname', 'email', 'active'
            email = member_info.get("email")

            # Skip "hidden" emails - these are typically app accounts
            if email and email != "hidden":
                emails.append(email)
            else:
                # For cloud, we might need to fetch user details separately
                try:
                    user = jira_client.user(id=account_id)

                    # Skip app accounts (bots, integrations, etc.)
                    if hasattr(user, "accountType") and user.accountType == "app":
                        logger.info(
                            f"Skipping app account {account_id} for group {group_name}"
                        )
                        continue

                    if hasattr(user, "emailAddress") and user.emailAddress:
                        emails.append(user.emailAddress)
                    else:
                        logger.warning(f"User {account_id} has no email address")
                except Exception as e:
                    logger.warning(
                        f"Could not fetch email for user {account_id} in group {group_name}: {e}"
                    )

    except Exception as e:
        logger.error(f"Error fetching members for group {group_name}: {e}")

    return emails


def _build_group_member_email_map(
    jira_client: JIRA,
) -> dict[str, set[str]]:
    """Build a map of group names to member emails."""
    group_member_emails: dict[str, set[str]] = {}

    try:
        # Get all groups from Jira - returns a list of group name strings
        group_names = jira_client.groups()

        if not group_names:
            logger.warning("No groups found in Jira")
            return group_member_emails

        logger.info(f"Found {len(group_names)} groups in Jira")

        for group_name in group_names:
            if not group_name:
                continue

            member_emails = _get_jira_group_members_email(
                jira_client=jira_client,
                group_name=group_name,
            )

            if member_emails:
                group_member_emails[group_name] = set(member_emails)
                logger.debug(
                    f"Found {len(member_emails)} members for group {group_name}"
                )
            else:
                logger.debug(f"No members found for group {group_name}")

    except Exception as e:
        logger.error(f"Error building group member email map: {e}")

    return group_member_emails


def jira_group_sync(
    tenant_id: str,
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    """
    Sync Jira groups and their members.

    This function fetches all groups from Jira and yields ExternalUserGroup
    objects containing the group ID and member emails.
    """
    jira_base_url = cc_pair.connector.connector_specific_config.get("jira_base_url", "")
    scoped_token = cc_pair.connector.connector_specific_config.get(
        "scoped_token", False
    )

    if not jira_base_url:
        logger.error("No jira_base_url found in connector config")
        return

    jira_client = build_jira_client(
        credentials=cc_pair.credential.credential_json,
        jira_base=jira_base_url,
        scoped_token=scoped_token,
    )

    group_member_email_map = _build_group_member_email_map(jira_client=jira_client)
    if not group_member_email_map:
        logger.error(f"No groups with members found for cc_pair_id={cc_pair.id}")

    for group_id, group_member_emails in group_member_email_map.items():
        yield ExternalUserGroup(
            id=group_id,
            user_emails=list(group_member_emails),
        )
