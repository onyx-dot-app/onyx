import json
from collections.abc import Generator
from typing import Any

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.utils import credential_json
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ATLASSIAN_ACCOUNT_TYPE = "atlassian"
_GROUP_MEMBER_PAGE_SIZE = 50

# The GET /group/member endpoint was introduced in Jira 6.0.
# Jira versions older than 6.0 do not have group management REST APIs at all.
_MIN_JIRA_VERSION_FOR_GROUP_MEMBER = "6.0"


class _JiraGroupNotFoundError(RuntimeError):
    pass


def _get_jira_error_text(error: JiraApiError) -> str:
    raw_text = error.text or ""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text

    if not isinstance(payload, dict):
        return raw_text

    error_messages = payload.get("errorMessages")
    if isinstance(error_messages, list):
        return "; ".join(str(message) for message in error_messages)
    if error_messages:
        return str(error_messages)

    return raw_text


def _is_group_not_found_error(error: JiraApiError) -> bool:
    error_text = _get_jira_error_text(error).lower()
    return "the group named" in error_text and "does not exist" in error_text


def _fetch_group_member_page(
    source_operations: JiraSourceOperations,
    group_name: str,
    start_at: int,
) -> dict[str, Any]:
    """Fetch a single page from the non-deprecated GET /group/member endpoint."""
    try:
        return source_operations.get_group_members_page(
            group_name=group_name,
            start_at=start_at,
            max_results=_GROUP_MEMBER_PAGE_SIZE,
        )
    except JiraApiError as e:
        if e.status_code == 404:
            if _is_group_not_found_error(e):
                raise _JiraGroupNotFoundError(
                    f"Jira group '{group_name}' no longer exists"
                ) from e

            raise RuntimeError(
                f"GET /group/member returned 404 for group '{group_name}'. "
                f"This endpoint requires Jira {_MIN_JIRA_VERSION_FOR_GROUP_MEMBER}+. "
                f"If you are running a self-hosted Jira instance, please upgrade "
                f"to at least Jira {_MIN_JIRA_VERSION_FOR_GROUP_MEMBER}."
            ) from e
        raise


def _get_group_member_emails(
    source_operations: JiraSourceOperations,
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
            page = _fetch_group_member_page(source_operations, group_name, start_at)
        except _JiraGroupNotFoundError:
            logger.warning(
                "Jira returned group %s from groups() but /group/member says it no "
                "longer exists. Skipping.",
                group_name,
            )
            return set()
        except Exception as e:
            logger.error("Error fetching members for group %s: %s", group_name, e)
            raise

        members: list[dict[str, Any]] = page.get("values", [])
        for member in members:
            account_type = member.get("accountType")
            # On Jira DC < 9.0, accountType is absent; include those users.
            # On Cloud / DC 9.0+, filter to real user accounts only.
            if account_type is not None and account_type != _ATLASSIAN_ACCOUNT_TYPE:
                continue

            email = member.get("emailAddress")
            if email:
                emails.add(email)
            else:
                logger.warning(
                    "Atlassian user %s in group %s has no visible email address",
                    member.get("accountId", "unknown"),
                    group_name,
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

    source_operations = JiraSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, DocumentSource.JIRA.value, credential_json(cc_pair)
        ),
        connector_specific_config={
            "jira_base_url": jira_base_url,
            "scoped_token": scoped_token,
        },
    )

    group_names = source_operations.list_groups().group_names
    if not group_names:
        raise ValueError(f"No groups found for cc_pair_id={cc_pair.id}")

    logger.info("Found %s groups in Jira", len(group_names))

    for group_name in group_names:
        if not group_name:
            continue

        member_emails = _get_group_member_emails(
            source_operations=source_operations,
            group_name=group_name,
        )
        if not member_emails:
            logger.debug("No members found for group %s", group_name)
            continue

        logger.debug("Found %s members for group %s", len(member_emails), group_name)
        yield ExternalUserGroup(
            id=group_name,
            user_emails=list(member_emails),
        )
