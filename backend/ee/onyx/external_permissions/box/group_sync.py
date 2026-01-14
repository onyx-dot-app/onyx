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
        # Get all groups in the enterprise
        # Box API: GET /groups
        groups_response = box_client.groups.get_groups()

        for group in groups_response.entries:
            group_id = str(group.id)
            group_name = getattr(group, "name", None) or f"Group_{group_id}"

            logger.debug(f"Processing Box group: {group_name} (ID: {group_id})")

            # Get members of this group
            # Box API: GET /groups/{group_id}/memberships
            try:
                memberships_response = box_client.groups.get_group_memberships(
                    group_id=group_id
                )

                user_emails: set[str] = set()
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

    except Exception as e:
        logger.error(f"Error during Box group sync: {e}")
        raise
