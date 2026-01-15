from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.connectors.box.connector import BoxConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def box_group_sync(
    tenant_id: str,
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    """
    Sync Box groups and their members.

    This function fetches all groups from Box and yields ExternalUserGroup
    objects containing the group ID and member emails.
    """
    # Create Box connector and load credentials
    box_connector = BoxConnector(**cc_pair.connector.connector_specific_config)
    box_connector.load_credentials(cc_pair.credential.credential_json)

    box_client = box_connector.box_client

    logger.info("Starting Box group sync...")

    try:
        # Get all groups in the enterprise with pagination
        # Box API: GET /groups
        limit = 1000  # Box API max items per page
        marker: str | None = None
        page_num = 0

        while True:
            page_num += 1
            groups_response = box_client.groups.get_groups(
                limit=limit,
                marker=marker,
            )

            logger.debug(
                f"Box API groups page {page_num}: {len(groups_response.entries)} groups"
            )

            for group in groups_response.entries:
                group_id = str(group.id)
                group_name = getattr(group, "name", None) or f"Group_{group_id}"

                logger.debug(f"Processing Box group: {group_name} (ID: {group_id})")

                # Get members of this group with pagination
                # Box API: GET /groups/{group_id}/memberships
                try:
                    membership_limit = 1000  # Box API max items per page
                    membership_marker: str | None = None
                    membership_page_num = 0
                    user_emails: set[str] = set()

                    while True:
                        membership_page_num += 1
                        memberships_response = box_client.groups.get_group_memberships(
                            group_id=group_id,
                            limit=membership_limit,
                            marker=membership_marker,
                        )

                        logger.debug(
                            f"Box API memberships page {membership_page_num} for group {group_name}: "
                            f"{len(memberships_response.entries)} members"
                        )

                        for membership in memberships_response.entries:
                            user = getattr(membership, "user", None)
                            if user:
                                # Extract email from user object
                                email = getattr(user, "login", None) or getattr(
                                    user, "email", None
                                )
                                if email:
                                    user_emails.add(email)
                                else:
                                    logger.warning(
                                        f"Group member {getattr(user, 'id', 'unknown')} "
                                        f"has no email/login in group {group_name}"
                                    )

                        # Check for more membership pages
                        membership_next_marker = getattr(
                            memberships_response, "next_marker", None
                        )
                        if membership_next_marker:
                            membership_marker = membership_next_marker
                        else:
                            break

                    if user_emails:
                        logger.info(
                            f"Found {len(user_emails)} members in Box group {group_name}"
                        )
                        yield ExternalUserGroup(
                            id=group_id,
                            user_emails=list(user_emails),
                        )
                    else:
                        logger.warning(
                            f"Box group {group_name} (ID: {group_id}) has no members with emails"
                        )

                except Exception as e:
                    logger.error(
                        f"Error fetching members for Box group {group_name} (ID: {group_id}): {e}"
                    )
                    # Continue with other groups even if one fails

            # Check for more groups pages
            next_marker = getattr(groups_response, "next_marker", None)
            if next_marker:
                marker = next_marker
            else:
                break

    except Exception as e:
        logger.error(f"Error during Box group sync: {e}")
        raise
