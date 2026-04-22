import json
import time
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import List

import requests

from onyx.configs.app_configs import FRESHDESK_MAX_RETRIES
from onyx.configs.app_configs import FRESHDESK_PER_PAGE
from onyx.configs.app_configs import FRESHDESK_RATE_LIMIT_CAP_SECONDS
from onyx.configs.app_configs import FRESHDESK_RETRY_INTERVAL
from onyx.configs.app_configs import FRESHDESK_SERVER_ERROR_RETRY_DELAY
from onyx.configs.app_configs import FRESHDESK_TICKET_DELAY_SECONDS
from onyx.configs.app_configs import FRESHDESK_TICKETS_MAX_PAGE
from onyx.configs.app_configs import FRESHDESK_TICKETS_PAGE_DELAY_SECONDS
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FRESHDESK_ID_PREFIX = "FRESHDESK_"


_TICKET_FIELDS_TO_INCLUDE = {
    "fr_escalated",
    "spam",
    "priority",
    "source",
    "status",
    "type",
    "is_escalated",
    "tags",
    "nr_due_by",
    "nr_escalated",
    "cc_emails",
    "fwd_emails",
    "reply_cc_emails",
    "ticket_cc_emails",
    "support_email",
    "to_emails",
}

_SOURCE_NUMBER_TYPE_MAP: dict[int, str] = {
    1: "Email",
    2: "Portal",
    3: "Phone",
    7: "Chat",
    9: "Feedback Widget",
    10: "Outbound Email",
}

_PRIORITY_NUMBER_TYPE_MAP: dict[int, str] = {
    1: "low",
    2: "medium",
    3: "high",
    4: "urgent",
}

_STATUS_NUMBER_TYPE_MAP: dict[int, str] = {
    2: "open",
    3: "pending",
    4: "resolved",
    5: "closed",
    16: "Work in Progress",
    17: "Pending with CSM",
    18: "Pending with Customer",
    19: "Pending with Cloud",
}


def _parse_retry_after_seconds(value: str | None, default: int) -> int:
    """Parse Retry-After header (delay-seconds or HTTP-date per RFC 7231)."""
    if not value or not value.strip():
        return default
    value = value.strip()
    try:
        return int(value)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
        delta = retry_at - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))
    except (TypeError, ValueError):
        return default


def _request_with_retries(
    url: str,
    *,
    auth: tuple[str, str],
    params: dict | None = None,
    timeout: int | float = 30,
    max_retries: int | None = FRESHDESK_MAX_RETRIES,
    error_context: str = "resource",
    request_delay: float = 0,
) -> requests.Response:
    """GET with retries for retryable Freshdesk responses."""
    retry_count = 0
    while True:
        try:
            if request_delay:
                time.sleep(request_delay)
            response = requests.get(url, auth=auth, params=params, timeout=timeout)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching {error_context}: {e}")
            retry_count += 1
            if max_retries is not None and retry_count >= max_retries:
                raise
            time.sleep(FRESHDESK_SERVER_ERROR_RETRY_DELAY)
            continue

        if response.status_code == 429:
            retry_after = min(
                _parse_retry_after_seconds(
                    response.headers.get("Retry-After"), FRESHDESK_RETRY_INTERVAL
                ),
                FRESHDESK_RATE_LIMIT_CAP_SECONDS,
            )
            logger.warning(
                f"Rate limit exceeded for {error_context}. "
                f"Retrying after {retry_after} seconds..."
            )
            time.sleep(retry_after)
            retry_count += 1
        elif response.status_code == 500:
            logger.warning(
                f"Server error for {error_context}. "
                f"Retrying after {FRESHDESK_SERVER_ERROR_RETRY_DELAY} seconds..."
            )
            time.sleep(FRESHDESK_SERVER_ERROR_RETRY_DELAY)
            retry_count += 1
        else:
            response.raise_for_status()
            return response

        if max_retries is not None and retry_count >= max_retries:
            raise Exception(
                f"Failed to fetch {error_context} after {max_retries} retries"
            )


def _fetch_all_conversations(
    ticket_id: int, domain: str, api_key: str, password: str
) -> str:
    """Fetch full paginated conversation thread for a ticket."""
    base_url = (
        f"https://{domain}.freshdesk.com/api/v2/tickets/{ticket_id}/conversations"
    )
    params: dict[str, int] = {
        "per_page": FRESHDESK_PER_PAGE,
        "page": 1,
    }
    all_conversations: list[dict] = []

    while True:
        response = _request_with_retries(
            base_url,
            auth=(api_key, password),
            params=params,
            timeout=30,
            max_retries=FRESHDESK_MAX_RETRIES,
            error_context=f"conversations of ticket {ticket_id}",
        )
        conversations = response.json()
        if not conversations:
            break

        all_conversations.extend(conversations)
        logger.info(
            f"Fetched {len(conversations)} conversations from page {params['page']} "
            f"for ticket {ticket_id}"
        )

        if len(conversations) < params["per_page"]:
            break

        params["page"] += 1

    if not all_conversations:
        return " No conversations available."

    conversation_text = ""
    for count, conversation in enumerate(all_conversations, start=1):
        private_label = " (Private Note)" if conversation.get("private") else ""
        body_text = conversation.get("body_text", "No content available")
        conversation_text += (
            f" Conversation {count}{private_label}: "
            f"{parse_html_page_basic(body_text)}"
        )

    return conversation_text


def _create_metadata_from_ticket(
    ticket: dict, custom_field: dict, current_url: str, name: str
) -> dict:
    metadata: dict[str, str | list[str]] = {}
    # Combine all emails into a list so there are no repeated emails
    email_data: set[str] = set()

    for key, value in ticket.items():
        # Skip fields that aren't useful for embedding
        if key not in _TICKET_FIELDS_TO_INCLUDE:
            continue

        # Skip empty fields
        if not value or value == "[]":
            continue

        # Convert strings or lists to strings
        stringified_value: str | list[str]
        if isinstance(value, list):
            stringified_value = [str(item) for item in value]
        else:
            stringified_value = str(value)

        if "email" in key:
            if isinstance(stringified_value, list):
                email_data.update(stringified_value)
            else:
                email_data.add(stringified_value)
        else:
            metadata[key] = stringified_value

    if email_data:
        metadata["emails"] = list(email_data)

    # Convert source numbers to human-parsable string
    if source_number := ticket.get("source"):
        metadata["source"] = _SOURCE_NUMBER_TYPE_MAP.get(
            source_number, "Unknown Source Type"
        )

    # Convert priority numbers to human-parsable string
    if priority_number := ticket.get("priority"):
        metadata["priority"] = _PRIORITY_NUMBER_TYPE_MAP.get(
            priority_number, "Unknown Priority"
        )

    # Convert status to human-parsable string
    if status_number := ticket.get("status"):
        metadata["status"] = _STATUS_NUMBER_TYPE_MAP.get(
            status_number, "Unknown Status"
        )

    if ticket_id := ticket.get("id"):
        metadata["id"] = str(ticket_id)

    metadata["created_at"] = ticket.get("created_at", "")
    metadata["updated_at"] = ticket.get("updated_at", "")
    metadata["subject"] = ticket.get("subject", "")

    try:
        due_by = datetime.fromisoformat(ticket.get("due_by", "").replace("Z", "+00:00"))
        metadata["overdue"] = str(datetime.now(timezone.utc) > due_by)
    except (TypeError, ValueError):
        metadata["overdue"] = ""

    metadata["title"] = str(custom_field.get("ticket_summary", ""))
    metadata["current_url"] = current_url
    metadata["connector_name"] = name

    return metadata


def _create_doc_from_ticket(
    ticket: dict, domain: str, api_key: str, password: str, name: str
) -> list[Document]:
    base_url = f"https://{domain}.freshdesk.com/api/v2/tickets/{ticket['id']}"
    logger.info(f"Indexing ticket {ticket['id']}")

    response = _request_with_retries(
        base_url,
        auth=(api_key, password),
        timeout=30,
        max_retries=FRESHDESK_MAX_RETRIES,
        error_context=f"ticket {ticket['id']}",
    )
    indv_ticket = response.json()

    priority = ""
    if priority_number := ticket.get("priority"):
        priority = _PRIORITY_NUMBER_TYPE_MAP.get(priority_number, "Unknown Priority")

    status = ""
    if status_number := ticket.get("status"):
        status = _STATUS_NUMBER_TYPE_MAP.get(status_number, "Unknown Status")

    text = (
        f"Ticket ID: {ticket.get('id', '')}, Status: {status}, Priority: {priority}, "
    )

    custom_field = indv_ticket.get("custom_fields") or {}
    if custom_field:
        component = custom_field.get("cf_components", "")
        kb_category = custom_field.get("cf_kb_category", "")
        product_category = custom_field.get("cf_product_category", "")
        resolution_type = custom_field.get("cf_resolution_type", "")
        region = custom_field.get("cf_region", "")
        customer = custom_field.get("cf_sd_customer", "")
        severity = custom_field.get("severity", "")
        ticket_summary = custom_field.get("ticket_summary", "")

        text += (
            f"Component: {component}, KB Category: {kb_category}, "
            f"Product Category: {product_category}, Resolution Type: {resolution_type}, Region: {region}, "
            f"Customer: {customer}, Severity: {severity}, Ticket Summary: {ticket_summary}"
        )

    description_text = indv_ticket.get("description_text", "")
    text += f"Ticket Description: {parse_html_page_basic(description_text)}"

    text += " Conversations:"
    text += _fetch_all_conversations(ticket["id"], domain, api_key, password)

    solution_provided = custom_field.get("solution_provided")
    if solution_provided:
        text += f" Solution Provided: {parse_html_page_basic(solution_provided)}"

    kb_articles_referred = custom_field.get("cf_kb_articles_referred")
    if kb_articles_referred:
        text += (
            " KB Article Referred for the Solution: "
            f"{parse_html_page_basic(kb_articles_referred)}"
        )

    # This is also used in the ID because it is more unique than the just the ticket ID
    link = f"https://{domain}.freshdesk.com/helpdesk/tickets/{ticket['id']}"
    metadata = _create_metadata_from_ticket(ticket, custom_field, link, name)

    updated_at = ticket.get("updated_at")
    doc_updated_at = (
        datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if updated_at
        else datetime.now(timezone.utc)
    )

    main_doc = Document(
        id=_FRESHDESK_ID_PREFIX + link,
        sections=[
            TextSection(
                link=link,
                text=text,
            )
        ],
        source=DocumentSource.FRESHDESK,
        semantic_identifier=ticket.get("subject", "None"),
        metadata=metadata,
        doc_updated_at=doc_updated_at,
    )
    return [main_doc]


class FreshdeskConnector(PollConnector, LoadConnector):
    name: str | None = None

    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self.name = "freshdesk"
        self.api_key: str | None = None
        self.domain: str | None = None
        self.password: str | None = None

    def load_credentials(self, credentials: dict[str, str | int]) -> None:
        api_key = credentials.get("freshdesk_api_key")
        domain = credentials.get("freshdesk_domain")
        password = credentials.get("freshdesk_password")

        password_to_use = (
            str(password) if isinstance(password, str) and password else "X"
        )
        if not all(
            isinstance(cred, str) for cred in [domain, api_key, password_to_use]
        ):
            raise ConnectorMissingCredentialError(
                "All Freshdesk credentials must be strings"
            )

        # Clean and normalize the domain URL
        domain = str(domain).strip().lower()
        domain = domain.rstrip("/")
        if domain.startswith(("http://", "https://")):
            domain = domain.replace("http://", "").replace("https://", "")
        if ".freshdesk.com" in domain:
            domain = domain.split(".freshdesk.com")[0]
        if not domain:
            raise ConnectorMissingCredentialError("Freshdesk domain cannot be empty")

        self.api_key = str(api_key)
        self.domain = domain
        self.password = password_to_use

    def _fetch_tickets(
        self,
        start: datetime | None = None,
        end: datetime | None = None,  # noqa: ARG002
    ) -> Iterator[List[dict]]:
        """
        'end' is not currently used, so we may double fetch tickets created after the indexing
        starts but before the actual call is made.

        To use 'end' would require us to use the search endpoint but it has limitations,
        namely having to fetch all IDs and then individually fetch each ticket because there is no
        'include' field available for this endpoint:
        https://developers.freshdesk.com/api/#filter_tickets
        """
        if self.api_key is None or self.domain is None or self.password is None:
            raise ConnectorMissingCredentialError("freshdesk")

        base_url = f"https://{self.domain}.freshdesk.com/api/v2/tickets"
        params: dict[str, int | str] = {
            "include": "description",
            "per_page": FRESHDESK_PER_PAGE,
            "page": 1,
        }

        if start:
            params["updated_since"] = start.isoformat()

        updated_since_anchor: str | None = params.get("updated_since")
        last_updated_at_from_max_page: str | None = None

        while True:
            response = _request_with_retries(
                base_url,
                auth=(self.api_key, self.password),
                params=params,
                timeout=30,
                max_retries=FRESHDESK_MAX_RETRIES,
                error_context="tickets list",
            )

            if response.status_code == 204:
                break

            tickets = json.loads(response.content)
            logger.info(
                f"Fetched {len(tickets)} tickets from Freshdesk API (Page {params['page']})"
            )

            if params["page"] == FRESHDESK_TICKETS_MAX_PAGE and tickets:
                last_ticket = tickets[-1]
                last_updated_at_from_max_page = last_ticket.get("updated_at")
                logger.info(
                    f"Stored last_updated_at from page {params['page']}: "
                    f"{last_updated_at_from_max_page}"
                )

            time.sleep(FRESHDESK_TICKETS_PAGE_DELAY_SECONDS)
            yield tickets

            if len(tickets) < int(params["per_page"]):
                break

            params["page"] = int(params["page"]) + 1

            if params["page"] == FRESHDESK_TICKETS_MAX_PAGE + 1:
                if not last_updated_at_from_max_page:
                    logger.error(
                        f"No last_updated_at available from page {FRESHDESK_TICKETS_MAX_PAGE}, "
                        "stopping pagination"
                    )
                    break
                if last_updated_at_from_max_page == updated_since_anchor:
                    logger.warning(
                        "updated_since anchor unchanged after page limit — "
                        "possible infinite loop (e.g. many tickets with same updated_at), stopping"
                    )
                    break
                logger.warning(
                    f"Reached page limit ({FRESHDESK_TICKETS_MAX_PAGE}) for Freshdesk API. "
                    "Resetting to page 1 with new updated_since"
                )
                updated_since_anchor = last_updated_at_from_max_page
                params["page"] = 1
                params["updated_since"] = last_updated_at_from_max_page
                last_updated_at_from_max_page = None
                logger.info(f"Continuing with updated_since: {updated_since_anchor}")

    def _process_tickets(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        doc_batch: List[Document] = []

        try:
            for ticket_batch in self._fetch_tickets(start, end):
                if not ticket_batch:
                    continue

                for ticket in ticket_batch:
                    try:
                        ticket_documents = _create_doc_from_ticket(
                            ticket, self.domain, self.api_key, self.password, self.name
                        )

                        if ticket_documents:
                            doc_batch.extend(ticket_documents)
                            logger.info(
                                f"Added {len(ticket_documents)} documents for ticket "
                                f"{ticket['id']} to batch"
                            )
                        else:
                            logger.warning(
                                f"No documents created for ticket {ticket['id']} - likely skipped due to errors"
                            )
                    except Exception as e:
                        logger.error(f"Error processing ticket {ticket['id']}: {e}")
                        continue

                    # Small delay between tickets to reduce rate-limit pressure
                    time.sleep(FRESHDESK_TICKET_DELAY_SECONDS)

                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch = []

            if doc_batch:
                yield doc_batch
        except Exception as e:
            logger.error(f"Critical error in ticket processing: {e}")
            raise

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_tickets()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        logger.debug(f"start time: {start_datetime} and end_datetime: {end_datetime}")

        yield from self._process_tickets(start_datetime, end_datetime)
