from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from hubspot import HubSpot  # type: ignore

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

HUBSPOT_BASE_URL = "https://app.hubspot.com/contacts/"
HUBSPOT_API_URL = "https://api.hubapi.com/integrations/v1/me"

logger = setup_logger()


class HubSpotConnector(LoadConnector, PollConnector):
    def __init__(
        self, batch_size: int = INDEX_BATCH_SIZE, access_token: str | None = None
    ) -> None:
        self.batch_size = batch_size
        self.access_token = access_token
        self.portal_id: str | None = None
        self.ticket_base_url = HUBSPOT_BASE_URL

    def get_portal_id(self) -> str:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        response = requests.get(HUBSPOT_API_URL, headers=headers)
        if response.status_code != 200:
            raise Exception("Error fetching portal ID")

        data = response.json()
        return data["portalId"]

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.access_token = credentials["hubspot_access_token"]

        if self.access_token:
            self.portal_id = self.get_portal_id()
            self.ticket_base_url = f"{HUBSPOT_BASE_URL}{self.portal_id}/ticket/"

        return None

    def _process_tickets(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.access_token is None:
            raise ConnectorMissingCredentialError("HubSpot")

        api_client = HubSpot(access_token=self.access_token)
        all_tickets = api_client.crm.tickets.get_all(associations=["contacts", "notes"])

        doc_batch: list[Document] = []

        for ticket in all_tickets:
            updated_at = ticket.updated_at.replace(tzinfo=None)
            if start is not None and updated_at < start:
                continue
            if end is not None and updated_at > end:
                continue

            title = ticket.properties["subject"]
            link = self.ticket_base_url + ticket.id
            content_text = ticket.properties["content"]

            associated_emails: list[str] = []
            associated_notes: list[str] = []

            if ticket.associations:
                contacts = ticket.associations.get("contacts")
                notes = ticket.associations.get("notes")

                if contacts:
                    for contact in contacts.results:
                        contact = api_client.crm.contacts.basic_api.get_by_id(
                            contact_id=contact.id
                        )
                        email = contact.properties.get("email")
                        if email is not None:
                            associated_emails.append(email)

                if notes:
                    for note in notes.results:
                        note = api_client.crm.objects.notes.basic_api.get_by_id(
                            note_id=note.id, properties=["content", "hs_body_preview"]
                        )
                        preview = note.properties.get("hs_body_preview")
                        if preview is not None:
                            associated_notes.append(preview)

            associated_emails_str = " ,".join(associated_emails)
            associated_notes_str = " ".join(associated_notes)

            content_text = f"{content_text}\n emails: {associated_emails_str} \n notes: {associated_notes_str}"

            doc_batch.append(
                Document(
                    id=ticket.id,
                    sections=[TextSection(link=link, text=content_text)],
                    source=DocumentSource.HUBSPOT,
                    semantic_identifier=title,
                    # Is already in tzutc, just replacing the timezone format
                    doc_updated_at=ticket.updated_at.replace(tzinfo=timezone.utc),
                    metadata={},
                )
            )

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
        start_datetime = datetime.utcfromtimestamp(start)
        end_datetime = datetime.utcfromtimestamp(end)
        return self._process_tickets(start_datetime, end_datetime)


if __name__ == "__main__":
    import os

    connector = HubSpotConnector()
    connector.load_credentials(
        {"hubspot_access_token": os.environ["HUBSPOT_ACCESS_TOKEN"]}
    )

    document_batches = connector.load_from_state()
    print(next(document_batches))
