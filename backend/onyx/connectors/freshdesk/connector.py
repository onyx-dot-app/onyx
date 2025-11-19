import json
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import List

import requests
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
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
}


# TODO: unify this with other generic rate limited requests with retries (e.g. Axero, Notion?)
@retry(tries=3, delay=1, backoff=2)
def _rate_limited_freshdesk_get(
    url: str, auth: tuple, params: dict
) -> requests.Response:
    return rl_requests.get(url, auth=auth, params=params)


def _create_metadata_from_ticket(ticket: dict) -> dict:
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

    due_by = datetime.fromisoformat(ticket["due_by"].replace("Z", "+00:00"))
    metadata["overdue"] = str(datetime.now(timezone.utc) > due_by)

    return metadata


def _create_doc_from_ticket(ticket: dict, domain: str) -> Document:
    # Use the ticket description as the text
    text = f"Ticket description: {parse_html_page_basic(ticket.get('description_text', ''))}"
    metadata = _create_metadata_from_ticket(ticket)

    # This is also used in the ID because it is more unique than the just the ticket ID
    link = f"https://{domain}.freshdesk.com/helpdesk/tickets/{ticket['id']}"

    return Document(
        id=_FRESHDESK_ID_PREFIX + link,
        sections=[
            TextSection(
                link=link,
                text=text,
            )
        ],
        source=DocumentSource.FRESHDESK,
        semantic_identifier=ticket["subject"],
        metadata=metadata,
        doc_updated_at=datetime.fromisoformat(
            ticket["updated_at"].replace("Z", "+00:00")
        ),
    )


class FreshdeskConnector(PollConnector, LoadConnector):
    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size

    def load_credentials(self, credentials: dict[str, str | int]) -> None:
        api_key = credentials.get("freshdesk_api_key")
        domain = credentials.get("freshdesk_domain")
        if not all(isinstance(cred, str) for cred in [domain, api_key]):
            raise ConnectorMissingCredentialError(
                "All Freshdesk credentials must be strings"
            )

        # TODO: Move the domain to the connector-specific configuration instead of part of the credential
        # Then apply normalization and validation against the config
        # Clean and normalize the domain URL
        domain = str(domain).strip().lower()

        # Remove any trailing slashes
        domain = domain.rstrip("/")

        # Remove protocol if present
        if domain.startswith(("http://", "https://")):
            domain = domain.replace("http://", "").replace("https://", "")

        # Remove .freshdesk.com suffix and any API paths if present
        if ".freshdesk.com" in domain:
            domain = domain.split(".freshdesk.com")[0]

        if not domain:
            raise ConnectorMissingCredentialError("Freshdesk domain cannot be empty")

        self.api_key = str(api_key)
        self.domain = domain

    def _fetch_tickets(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> Iterator[List[dict]]:
        """
        'end' is not currently used, so we may double fetch tickets created after the indexing
        starts but before the actual call is made.

        To use 'end' would require us to use the search endpoint but it has limitations,
        namely having to fetch all IDs and then individually fetch each ticket because there is no
        'include' field available for this endpoint:
        https://developers.freshdesk.com/api/#filter_tickets
        """
        if self.api_key is None or self.domain is None:
            raise ConnectorMissingCredentialError("freshdesk")

        base_url = f"https://{self.domain}.freshdesk.com/api/v2/tickets"
        params: dict[str, int | str] = {
            "include": "description",
            "per_page": 50,
            "page": 1,
        }

        if start:
            params["updated_since"] = start.isoformat()

        while True:
            # Freshdesk API uses API key as the username and any value as the password.
            response = _rate_limited_freshdesk_get(
                base_url,
                auth=(self.api_key, "CanYouBelieveFreshdeskDoesThis"),
                params=params,
            )
            response.raise_for_status()

            if response.status_code == 204:
                break

            tickets = json.loads(response.content)
            logger.info(
                f"Fetched {len(tickets)} tickets from Freshdesk API (Page {params['page']})"
            )

            yield tickets

            if len(tickets) < int(params["per_page"]):
                break

            params["page"] = int(params["page"]) + 1

    def _process_tickets(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        doc_batch: List[Document] = []

        for ticket_batch in self._fetch_tickets(start, end):
            for ticket in ticket_batch:
                doc_batch.append(_create_doc_from_ticket(ticket, self.domain))

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_tickets()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)

        yield from self._process_tickets(start_datetime, end_datetime)
