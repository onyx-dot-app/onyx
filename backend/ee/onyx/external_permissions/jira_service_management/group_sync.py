from collections.abc import Generator
from typing import Any

from jira import JIRA

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.jira.group_sync import _get_group_member_emails
from onyx.connectors.jira.utils import build_jira_client
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_API_BASE = "rest/servicedeskapi"
_JSM_SERVICEDESK_PATH = "servicedesk"
_JSM_CUSTOMER_PATH = "servicedesk/{service_desk_id}/customer"
_JSM_CUSTOMER_PAGE_SIZE = 50
_ATLASSIAN_ACCOUNT_TYPE = "atlassian"


def _get_service_desk_ids(jira_client: JIRA, project_key: str) -> list[int]:
    try:
        server = jira_client._options["server"].rstrip("/")
        url = f"{server}/{_JSM_API_BASE}/{_JSM_SERVICEDESK_PATH}"
        response = jira_client._session.get(url, params={"projectKey": project_key})
        response.raise_for_status()
        return [int(sd["id"]) for sd in response.json().get("values", [])]
    except Exception as e:
        logger.warning(
            f"Could not fetch service desk IDs for project '{project_key}': {e}"
        )
        return []


def _get_portal_customer_emails(
    jira_client: JIRA,
    service_desk_id: int,
) -> set[str]:
    emails: set[str] = set()
    start = 0
    server = jira_client._options["server"].rstrip("/")

    while True:
        try:
            url = (
                f"{server}/{_JSM_API_BASE}/"
                f"{_JSM_CUSTOMER_PATH.format(service_desk_id=service_desk_id)}"
            )
            r = jira_client._session.get(
                url, params={"start": start, "limit": _JSM_CUSTOMER_PAGE_SIZE}
            )
            r.raise_for_status()
            response: dict[str, Any] = r.json()
        except Exception as e:
            logger.warning(
                f"Could not fetch customers for service desk {service_desk_id}: {e}"
            )
            break

        values: list[dict[str, Any]] = response.get("values", [])
        for customer in values:
            account_type = customer.get("accountType")
            if account_type is not None and account_type != _ATLASSIAN_ACCOUNT_TYPE:
                continue
            email = customer.get("emailAddress")
            if email:
                emails.add(email)

        if response.get("isLastPage", True) or not values:
            break
        start += len(values)

    return emails


def jsm_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    config = cc_pair.connector.connector_specific_config
    jira_base_url = config.get("jira_base_url", "")
    jsm_project_key = config.get("jsm_project_key", "")
    scoped_token = config.get("scoped_token", False)

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

    # Part 1: Sync standard Jira groups (covers agents and internal users)
    group_names = jira_client.groups()
    if group_names:
        logger.info(f"Found {len(group_names)} groups in Jira for JSM sync")
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
            yield ExternalUserGroup(
                id=group_name,
                user_emails=list(member_emails),
            )

    # Part 2: Sync portal-only customers as a synthetic group so they can
    # find their own tickets via Onyx search.
    if jsm_project_key:
        service_desk_ids = _get_service_desk_ids(jira_client, jsm_project_key)
        for sd_id in service_desk_ids:
            customer_emails = _get_portal_customer_emails(jira_client, sd_id)
            if not customer_emails:
                logger.debug(
                    f"No portal customers found for service desk {sd_id}"
                )
                continue
            group_id = f"jsm_portal_customers_{jsm_project_key}"
            logger.info(
                f"Yielding portal customer group '{group_id}' with "
                f"{len(customer_emails)} members"
            )
            yield ExternalUserGroup(
                id=group_id,
                user_emails=list(customer_emails),
            )
