import json
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import List

import requests

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import ConnectorMissingCredentialError
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.file_processing.html_utils import parse_html_page_basic
from danswer.utils.logger import setup_logger

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
            Section(
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
        password = credentials.get("freshdesk_password")

        if not all(isinstance(cred, str) for cred in [domain, api_key, password]):
            raise ConnectorMissingCredentialError(
                "All Freshdesk credentials must be strings"
            )

        self.api_key = str(api_key)
        self.domain = str(domain)
        self.password = str(password)

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
        if self.api_key is None or self.domain is None or self.password is None:
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
            response = requests.get(
                base_url, auth=(self.api_key, self.password), params=params
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
