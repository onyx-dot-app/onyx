from collections.abc import Generator
from typing import Any

from jira import JIRA
from jira.exceptions import JIRAError

from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.connectors.jira.utils import build_jira_client
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ATLASSIAN_ACCOUNT_TYPE = "atlassian"
_GROUP_MEMBER_PAGE_SIZE = 50

# The GET /group/member endpoint was introduced in Jira 6.0.
# Jira versions older than 6.0 do not have group management REST APIs at all.
_MIN_JIRA_VERSION_FOR_GROUP_MEMBER = "6.0"


def _fetch_group_member_page(
    jira_client: JIRA,
    group_name: str,
    start_at: int,
) -> dict[str, Any]:
    """Fetch a single page from the non-deprecated GET /group/member endpoint.

    The old GET /group endpoint (used by jira_client.group_members()) is deprecated
    and decommissioned in Jira Server 10.3+. This uses the replacement endpoint
    directly via the library's internal _get_json helper, following the same pattern
    as enhanced_search_ids / bulk_fetch_issues in connector.py.

    There is an open PR to the library to switch to this endpoint since last year:
    https://github.com/pycontribs/jira/pull/2356
    so once it is merged and released, we can switch to using the library function.
    """
    try:
        return jira_client._get_json(
            "group/member",
            params={
                "groupname": group_name,
                "includeInactiveUsers": "false",
                "startAt": start_at,
                "maxResults": _GROUP_MEMBER_PAGE_SIZE,
            },
        )
    except JIRAError as e:
        if e.status_code == 404:
            raise RuntimeError(
                f"GET /group/member returned 404 for group '{group_name}'. "
                f"This endpoint requires Jira {_MIN_JIRA_VERSION_FOR_GROUP_MEMBER}+. "
                f"If you are running a self-hosted Jira instance, please upgrade "
                f"to at least Jira {_MIN_JIRA_VERSION_FOR_GROUP_MEMBER}."
            ) from e
        raise


def _get_group_member_emails(
    jira_client: JIRA,
    group_name: str,
) -> set[str]:
    """Get all member emails for a single Jira group.

    Uses the non-deprecated GET /group/member endpoint which returns full user
    objects including accountType, so we can filter out app/customer accounts
    without making separate user() calls.
    """
    emails: set[str] = set()
    start_at = 0

    while True:
        try:
            page = _fetch_group_member_page(jira_client, group_name, start_at)
        except Exception as e:
            logger.error(f"Error fetching members for group {group_name}: {e}")
            raise

        members: list[dict[str, Any]] = page.get("values", [])
        for member in members:
            if member.get("accountType") != _ATLASSIAN_ACCOUNT_TYPE:
                continue

            email = member.get("emailAddress")
            if email:
                emails.add(email)
            else:
                logger.warning(
                    f"Atlassian user {member.get('accountId', 'unknown')} "
                    f"in group {group_name} has no visible email address"
                )

        if page.get("isLast", True) or not members:
            break
        start_at += len(members)

    return emails


def jira_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    """Sync Jira groups and their members, yielding one group at a time.

    Streams group-by-group rather than accumulating all groups in memory.
    """
    jira_base_url = cc_pair.connector.connector_specific_config.get("jira_base_url", "")
    scoped_token = cc_pair.connector.connector_specific_config.get(
        "scoped_token", False
    )

    if not jira_base_url:
        raise ValueError("No jira_base_url found in connector config")

    credential_json = (
        cc_pair.credential.credential_json.get_value(apply_mask=False)
        if cc_pair.credential.credential_json
        else {}
    )
    jira_client = build_jira_client(
        credentials=credential_json,
        jira_base=jira_base_url,
        scoped_token=scoped_token,
    )

    group_names = jira_client.groups()
    if not group_names:
        raise ValueError(f"No groups found for cc_pair_id={cc_pair.id}")

    logger.info(f"Found {len(group_names)} groups in Jira")

    for group_name in group_names:
        if not group_name:
            continue

        member_emails = _get_group_member_emails(
            jira_client=jira_client,
            group_name=group_name,
        )
        if not member_emails:
            logger.debug(f"No members found for group {group_name}")
            continue

        logger.debug(f"Found {len(member_emails)} members for group {group_name}")
        yield ExternalUserGroup(
            id=group_name,
            user_emails=list(member_emails),
        )
