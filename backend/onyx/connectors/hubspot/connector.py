import re
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import TypeVar

import requests
from hubspot import HubSpot  # type: ignore

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.hubspot.rate_limit import HubSpotRateLimiter
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

HUBSPOT_BASE_URL = "https://app.hubspot.com"
HUBSPOT_API_URL = "https://api.hubapi.com/integrations/v1/me"

# Available HubSpot object types
AVAILABLE_OBJECT_TYPES = {"tickets", "companies", "deals", "contacts"}

HUBSPOT_PAGE_SIZE = 100

T = TypeVar("T")

logger = setup_logger()


class HubSpotConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        access_token: str | None = None,
        object_types: list[str] | None = None,
    ) -> None:
        self.batch_size = batch_size
        self._access_token = access_token
        self._portal_id: str | None = None
        self._rate_limiter = HubSpotRateLimiter()

        # Set object types to fetch, default to all available types
        if object_types is None:
            self.object_types = AVAILABLE_OBJECT_TYPES.copy()
        else:
            object_types_set = set(object_types)

            # Validate provided object types
            invalid_types = object_types_set - AVAILABLE_OBJECT_TYPES
            if invalid_types:
                raise ValueError(
                    f"Invalid object types: {invalid_types}. Available types: {AVAILABLE_OBJECT_TYPES}"
                )
            self.object_types = object_types_set.copy()

    @property
    def access_token(self) -> str:
        """Get the access token, raising an exception if not set."""
        if self._access_token is None:
            raise ConnectorMissingCredentialError("HubSpot access token not set")
        return self._access_token

    @access_token.setter
    def access_token(self, value: str | None) -> None:
        """Set the access token."""
        self._access_token = value

    @property
    def portal_id(self) -> str:
        """Get the portal ID, raising an exception if not set."""
        if self._portal_id is None:
            raise ConnectorMissingCredentialError("HubSpot portal ID not set")
        return self._portal_id

    @portal_id.setter
    def portal_id(self, value: str | None) -> None:
        """Set the portal ID."""
        self._portal_id = value

    def _call_hubspot(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return self._rate_limiter.call(func, *args, **kwargs)

    def _paginated_results(
        self,
        fetch_page: Callable[..., Any],
        **kwargs: Any,
    ) -> Generator[Any, None, None]:
        base_kwargs = dict(kwargs)
        base_kwargs.setdefault("limit", HUBSPOT_PAGE_SIZE)

        after: str | None = None
        while True:
            page_kwargs = base_kwargs.copy()
            if after is not None:
                page_kwargs["after"] = after

            page = self._call_hubspot(fetch_page, **page_kwargs)
            results = getattr(page, "results", [])
            for result in results:
                yield result

            paging = getattr(page, "paging", None)
            next_page = getattr(paging, "next", None) if paging else None
            if next_page is None:
                break

            after = getattr(next_page, "after", None)
            if after is None:
                break

    def _clean_html_content(self, html_content: str) -> str:
        """Clean HTML content and extract raw text"""
        if not html_content:
            return ""

        # Remove HTML tags using regex
        clean_text = re.sub(r"<[^>]+>", "", html_content)

        # Decode common HTML entities
        clean_text = clean_text.replace("&nbsp;", " ")
        clean_text = clean_text.replace("&amp;", "&")
        clean_text = clean_text.replace("&lt;", "<")
        clean_text = clean_text.replace("&gt;", ">")
        clean_text = clean_text.replace("&quot;", '"')
        clean_text = clean_text.replace("&#39;", "'")

        # Clean up whitespace
        clean_text = " ".join(clean_text.split())

        return clean_text.strip()

    def get_portal_id(self) -> str:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        response = requests.get(HUBSPOT_API_URL, headers=headers)
        if response.status_code != 200:
            raise Exception("Error fetching portal ID")

        data = response.json()
        return str(data["portalId"])

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.access_token = cast(str, credentials["hubspot_access_token"])
        self.portal_id = self.get_portal_id()
        return None

    def _get_object_url(self, object_type: str, object_id: str) -> str:
        """Generate HubSpot URL for different object types"""
        if object_type == "tickets":
            return (
                f"{HUBSPOT_BASE_URL}/contacts/{self.portal_id}/record/0-5/{object_id}"
            )
        elif object_type == "companies":
            return (
                f"{HUBSPOT_BASE_URL}/contacts/{self.portal_id}/record/0-2/{object_id}"
            )
        elif object_type == "deals":
            return (
                f"{HUBSPOT_BASE_URL}/contacts/{self.portal_id}/record/0-3/{object_id}"
            )
        elif object_type == "contacts":
            return (
                f"{HUBSPOT_BASE_URL}/contacts/{self.portal_id}/record/0-1/{object_id}"
            )
        elif object_type == "notes":
            return (
                f"{HUBSPOT_BASE_URL}/contacts/{self.portal_id}/objects/0-4/{object_id}"
            )
        else:
            return f"{HUBSPOT_BASE_URL}/contacts/{self.portal_id}/{object_type}/{object_id}"

    def _get_associated_objects(
        self,
        api_client: HubSpot,
        object_id: str,
        from_object_type: str,
        to_object_type: str,
    ) -> list[dict[str, Any]]:
        """Get associated objects for a given object"""
        try:
            associations_iter = self._paginated_results(
                api_client.crm.associations.v4.basic_api.get_page,
                object_type=from_object_type,
                object_id=object_id,
                to_object_type=to_object_type,
            )

            object_ids = [assoc.to_object_id for assoc in associations_iter]

            associated_objects: list[dict[str, Any]] = []

            if to_object_type == "contacts":
                for obj_id in object_ids:
                    try:
                        obj = self._call_hubspot(
                            api_client.crm.contacts.basic_api.get_by_id,
                            contact_id=obj_id,
                            properties=[
                                "firstname",
                                "lastname",
                                "email",
                                "company",
                                "jobtitle",
                            ],
                        )
                        associated_objects.append(obj.to_dict())
                    except Exception as e:
                        logger.warning(f"Failed to fetch contact {obj_id}: {e}")

            elif to_object_type == "companies":
                for obj_id in object_ids:
                    try:
                        obj = self._call_hubspot(
                            api_client.crm.companies.basic_api.get_by_id,
                            company_id=obj_id,
                            properties=[
                                "name",
                                "domain",
                                "industry",
                                "city",
                                "state",
                            ],
                        )
                        associated_objects.append(obj.to_dict())
                    except Exception as e:
                        logger.warning(f"Failed to fetch company {obj_id}: {e}")

            elif to_object_type == "deals":
                for obj_id in object_ids:
                    try:
                        obj = self._call_hubspot(
                            api_client.crm.deals.basic_api.get_by_id,
                            deal_id=obj_id,
                            properties=[
                                "dealname",
                                "amount",
                                "dealstage",
                                "closedate",
                                "pipeline",
                            ],
                        )
                        associated_objects.append(obj.to_dict())
                    except Exception as e:
                        logger.warning(f"Failed to fetch deal {obj_id}: {e}")

            elif to_object_type == "tickets":
                for obj_id in object_ids:
                    try:
                        obj = self._call_hubspot(
                            api_client.crm.tickets.basic_api.get_by_id,
                            ticket_id=obj_id,
                            properties=["subject", "content", "hs_ticket_priority"],
                        )
                        associated_objects.append(obj.to_dict())
                    except Exception as e:
                        logger.warning(f"Failed to fetch ticket {obj_id}: {e}")

            return associated_objects

        except Exception as e:
            logger.warning(
                f"Failed to get associations from {from_object_type} to {to_object_type}: {e}"
            )
            return []

    def _get_associated_notes(
        self,
        api_client: HubSpot,
        object_id: str,
        object_type: str,
    ) -> list[dict[str, Any]]:
        """Get notes associated with a given object"""
        try:
            associations_iter = self._paginated_results(
                api_client.crm.associations.v4.basic_api.get_page,
                object_type=object_type,
                object_id=object_id,
                to_object_type="notes",
            )

            note_ids = [assoc.to_object_id for assoc in associations_iter]

            associated_notes = []

            for note_id in note_ids:
                try:
                    # Notes are engagements in HubSpot, use the engagements API
                    note = self._call_hubspot(
                        api_client.crm.objects.notes.basic_api.get_by_id,
                        note_id=note_id,
                        properties=[
                            "hs_note_body",
                            "hs_timestamp",
                            "hs_created_by",
                            "hubspot_owner_id",
                        ],
                    )
                    associated_notes.append(note.to_dict())
                except Exception as e:
                    logger.warning(f"Failed to fetch note {note_id}: {e}")

            return associated_notes

        except Exception as e:
            logger.warning(f"Failed to get notes for {object_type} {object_id}: {e}")
            return []

    def _create_object_section(
        self, obj: dict[str, Any], object_type: str
    ) -> TextSection:
        """Create a TextSection for an associated object"""
        obj_id = obj.get("id", "")
        properties = obj.get("properties", {})

        if object_type == "contacts":
            name_parts = []
            if properties.get("firstname"):
                name_parts.append(properties["firstname"])
            if properties.get("lastname"):
                name_parts.append(properties["lastname"])

            if name_parts:
                name = " ".join(name_parts)
            elif properties.get("email"):
                # Use email as fallback if no first/last name
                name = properties["email"]
            else:
                name = "Unknown Contact"

            content_parts = [f"Contact: {name}"]
            if properties.get("email"):
                content_parts.append(f"Email: {properties['email']}")
            if properties.get("company"):
                content_parts.append(f"Company: {properties['company']}")
            if properties.get("jobtitle"):
                content_parts.append(f"Job Title: {properties['jobtitle']}")

        elif object_type == "companies":
            name = properties.get("name", "Unknown Company")
            content_parts = [f"Company: {name}"]
            if properties.get("domain"):
                content_parts.append(f"Domain: {properties['domain']}")
            if properties.get("industry"):
                content_parts.append(f"Industry: {properties['industry']}")
            if properties.get("city") and properties.get("state"):
                content_parts.append(
                    f"Location: {properties['city']}, {properties['state']}"
                )

        elif object_type == "deals":
            name = properties.get("dealname", "Unknown Deal")
            content_parts = [f"Deal: {name}"]
            if properties.get("amount"):
                content_parts.append(f"Amount: ${properties['amount']}")
            if properties.get("dealstage"):
                content_parts.append(f"Stage: {properties['dealstage']}")
            if properties.get("closedate"):
                content_parts.append(f"Close Date: {properties['closedate']}")
            if properties.get("pipeline"):
                content_parts.append(f"Pipeline: {properties['pipeline']}")

        elif object_type == "tickets":
            name = properties.get("subject", "Unknown Ticket")
            content_parts = [f"Ticket: {name}"]
            if properties.get("content"):
                content_parts.append(f"Content: {properties['content']}")
            if properties.get("hs_ticket_priority"):
                content_parts.append(f"Priority: {properties['hs_ticket_priority']}")
        elif object_type == "notes":
            # Notes have a body property that contains the note content
            body = properties.get("hs_note_body", "")
            timestamp = properties.get("hs_timestamp", "")

            # Clean HTML content to get raw text
            clean_body = self._clean_html_content(body)

            # Use full content, not truncated
            content_parts = [f"Note: {clean_body}"]
            if timestamp:
                content_parts.append(f"Created: {timestamp}")
        else:
            content_parts = [f"{object_type.capitalize()}: {obj_id}"]

        content = "\n".join(content_parts)
        link = self._get_object_url(object_type, obj_id)

        return TextSection(link=link, text=content)

    def _process_tickets(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        api_client = HubSpot(access_token=self.access_token)

        tickets_iter = self._paginated_results(
            api_client.crm.tickets.basic_api.get_page,
            properties=[
                "subject",
                "content",
                "hs_ticket_priority",
                "createdate",
                "hs_lastmodifieddate",
            ],
            associations=["contacts", "companies", "deals"],
        )

        doc_batch: list[Document] = []

        for ticket in tickets_iter:
            updated_at = ticket.updated_at.replace(tzinfo=None)
            if start is not None and updated_at < start.replace(tzinfo=None):
                continue
            if end is not None and updated_at > end.replace(tzinfo=None):
                continue

            title = ticket.properties.get("subject") or f"Ticket {ticket.id}"
            link = self._get_object_url("tickets", ticket.id)
            content_text = ticket.properties.get("content", "")

            # Main ticket section
            sections = [TextSection(link=link, text=content_text)]

            # Metadata with parent object IDs
            metadata: dict[str, str | list[str]] = {
                "object_type": "ticket",
            }

            if ticket.properties.get("hs_ticket_priority"):
                metadata["priority"] = ticket.properties["hs_ticket_priority"]

            # Add associated objects as sections
            associated_contact_ids = []
            associated_company_ids = []
            associated_deal_ids = []

            # Get associated contacts
            associated_contacts = self._get_associated_objects(
                api_client, ticket.id, "tickets", "contacts"
            )
            for contact in associated_contacts:
                sections.append(self._create_object_section(contact, "contacts"))
                associated_contact_ids.append(contact["id"])

            # Get associated companies
            associated_companies = self._get_associated_objects(
                api_client, ticket.id, "tickets", "companies"
            )
            for company in associated_companies:
                sections.append(self._create_object_section(company, "companies"))
                associated_company_ids.append(company["id"])

            # Get associated deals
            associated_deals = self._get_associated_objects(
                api_client, ticket.id, "tickets", "deals"
            )
            for deal in associated_deals:
                sections.append(self._create_object_section(deal, "deals"))
                associated_deal_ids.append(deal["id"])

            # Get associated notes
            associated_notes = self._get_associated_notes(
                api_client, ticket.id, "tickets"
            )
            for note in associated_notes:
                sections.append(self._create_object_section(note, "notes"))

            # Add association IDs to metadata
            if associated_contact_ids:
                metadata["associated_contact_ids"] = associated_contact_ids
            if associated_company_ids:
                metadata["associated_company_ids"] = associated_company_ids
            if associated_deal_ids:
                metadata["associated_deal_ids"] = associated_deal_ids

            doc_batch.append(
                Document(
                    id=f"hubspot_ticket_{ticket.id}",
                    sections=cast(list[TextSection | ImageSection], sections),
                    source=DocumentSource.HUBSPOT,
                    semantic_identifier=title,
                    doc_updated_at=ticket.updated_at.replace(tzinfo=timezone.utc),
                    metadata=metadata,
                )
            )

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def _process_companies(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        api_client = HubSpot(access_token=self.access_token)

        companies_iter = self._paginated_results(
            api_client.crm.companies.basic_api.get_page,
            properties=[
                "name",
                "domain",
                "industry",
                "city",
                "state",
                "description",
                "createdate",
                "hs_lastmodifieddate",
            ],
            associations=["contacts", "deals", "tickets"],
        )

        doc_batch: list[Document] = []

        for company in companies_iter:
            updated_at = company.updated_at.replace(tzinfo=None)
            if start is not None and updated_at < start.replace(tzinfo=None):
                continue
            if end is not None and updated_at > end.replace(tzinfo=None):
                continue

            title = company.properties.get("name") or f"Company {company.id}"
            link = self._get_object_url("companies", company.id)

            # Build main content
            content_parts = [f"Company: {title}"]
            if company.properties.get("domain"):
                content_parts.append(f"Domain: {company.properties['domain']}")
            if company.properties.get("industry"):
                content_parts.append(f"Industry: {company.properties['industry']}")
            if company.properties.get("city") and company.properties.get("state"):
                content_parts.append(
                    f"Location: {company.properties['city']}, {company.properties['state']}"
                )
            if company.properties.get("description"):
                content_parts.append(
                    f"Description: {company.properties['description']}"
                )

            content_text = "\n".join(content_parts)

            # Main company section
            sections = [TextSection(link=link, text=content_text)]

            # Metadata with parent object IDs
            metadata: dict[str, str | list[str]] = {
                "company_id": company.id,
                "object_type": "company",
            }

            if company.properties.get("industry"):
                metadata["industry"] = company.properties["industry"]
            if company.properties.get("domain"):
                metadata["domain"] = company.properties["domain"]

            # Add associated objects as sections
            associated_contact_ids = []
            associated_deal_ids = []
            associated_ticket_ids = []

            # Get associated contacts
            associated_contacts = self._get_associated_objects(
                api_client, company.id, "companies", "contacts"
            )
            for contact in associated_contacts:
                sections.append(self._create_object_section(contact, "contacts"))
                associated_contact_ids.append(contact["id"])

            # Get associated deals
            associated_deals = self._get_associated_objects(
                api_client, company.id, "companies", "deals"
            )
            for deal in associated_deals:
                sections.append(self._create_object_section(deal, "deals"))
                associated_deal_ids.append(deal["id"])

            # Get associated tickets
            associated_tickets = self._get_associated_objects(
                api_client, company.id, "companies", "tickets"
            )
            for ticket in associated_tickets:
                sections.append(self._create_object_section(ticket, "tickets"))
                associated_ticket_ids.append(ticket["id"])

            # Get associated notes
            associated_notes = self._get_associated_notes(
                api_client, company.id, "companies"
            )
            for note in associated_notes:
                sections.append(self._create_object_section(note, "notes"))

            # Add association IDs to metadata
            if associated_contact_ids:
                metadata["associated_contact_ids"] = associated_contact_ids
            if associated_deal_ids:
                metadata["associated_deal_ids"] = associated_deal_ids
            if associated_ticket_ids:
                metadata["associated_ticket_ids"] = associated_ticket_ids

            doc_batch.append(
                Document(
                    id=f"hubspot_company_{company.id}",
                    sections=cast(list[TextSection | ImageSection], sections),
                    source=DocumentSource.HUBSPOT,
                    semantic_identifier=title,
                    doc_updated_at=company.updated_at.replace(tzinfo=timezone.utc),
                    metadata=metadata,
                )
            )

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def _process_deals(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        api_client = HubSpot(access_token=self.access_token)

        deals_iter = self._paginated_results(
            api_client.crm.deals.basic_api.get_page,
            properties=[
                "dealname",
                "amount",
                "dealstage",
                "closedate",
                "pipeline",
                "description",
                "createdate",
                "hs_lastmodifieddate",
            ],
            associations=["contacts", "companies", "tickets"],
        )

        doc_batch: list[Document] = []

        for deal in deals_iter:
            updated_at = deal.updated_at.replace(tzinfo=None)
            if start is not None and updated_at < start.replace(tzinfo=None):
                continue
            if end is not None and updated_at > end.replace(tzinfo=None):
                continue

            title = deal.properties.get("dealname") or f"Deal {deal.id}"
            link = self._get_object_url("deals", deal.id)

            # Build main content
            content_parts = [f"Deal: {title}"]
            if deal.properties.get("amount"):
                content_parts.append(f"Amount: ${deal.properties['amount']}")
            if deal.properties.get("dealstage"):
                content_parts.append(f"Stage: {deal.properties['dealstage']}")
            if deal.properties.get("closedate"):
                content_parts.append(f"Close Date: {deal.properties['closedate']}")
            if deal.properties.get("pipeline"):
                content_parts.append(f"Pipeline: {deal.properties['pipeline']}")
            if deal.properties.get("description"):
                content_parts.append(f"Description: {deal.properties['description']}")

            content_text = "\n".join(content_parts)

            # Main deal section
            sections = [TextSection(link=link, text=content_text)]

            # Metadata with parent object IDs
            metadata: dict[str, str | list[str]] = {
                "deal_id": deal.id,
                "object_type": "deal",
            }

            if deal.properties.get("dealstage"):
                metadata["deal_stage"] = deal.properties["dealstage"]
            if deal.properties.get("pipeline"):
                metadata["pipeline"] = deal.properties["pipeline"]
            if deal.properties.get("amount"):
                metadata["amount"] = deal.properties["amount"]

            # Add associated objects as sections
            associated_contact_ids = []
            associated_company_ids = []
            associated_ticket_ids = []

            # Get associated contacts
            associated_contacts = self._get_associated_objects(
                api_client, deal.id, "deals", "contacts"
            )
            for contact in associated_contacts:
                sections.append(self._create_object_section(contact, "contacts"))
                associated_contact_ids.append(contact["id"])

            # Get associated companies
            associated_companies = self._get_associated_objects(
                api_client, deal.id, "deals", "companies"
            )
            for company in associated_companies:
                sections.append(self._create_object_section(company, "companies"))
                associated_company_ids.append(company["id"])

            # Get associated tickets
            associated_tickets = self._get_associated_objects(
                api_client, deal.id, "deals", "tickets"
            )
            for ticket in associated_tickets:
                sections.append(self._create_object_section(ticket, "tickets"))
                associated_ticket_ids.append(ticket["id"])

            # Get associated notes
            associated_notes = self._get_associated_notes(api_client, deal.id, "deals")
            for note in associated_notes:
                sections.append(self._create_object_section(note, "notes"))

            # Add association IDs to metadata
            if associated_contact_ids:
                metadata["associated_contact_ids"] = associated_contact_ids
            if associated_company_ids:
                metadata["associated_company_ids"] = associated_company_ids
            if associated_ticket_ids:
                metadata["associated_ticket_ids"] = associated_ticket_ids

            doc_batch.append(
                Document(
                    id=f"hubspot_deal_{deal.id}",
                    sections=cast(list[TextSection | ImageSection], sections),
                    source=DocumentSource.HUBSPOT,
                    semantic_identifier=title,
                    doc_updated_at=deal.updated_at.replace(tzinfo=timezone.utc),
                    metadata=metadata,
                )
            )

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def _process_contacts(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        api_client = HubSpot(access_token=self.access_token)

        contacts_iter = self._paginated_results(
            api_client.crm.contacts.basic_api.get_page,
            properties=[
                "firstname",
                "lastname",
                "email",
                "company",
                "jobtitle",
                "phone",
                "city",
                "state",
                "createdate",
                "lastmodifieddate",
            ],
            associations=["companies", "deals", "tickets"],
        )

        doc_batch: list[Document] = []

        for contact in contacts_iter:
            updated_at = contact.updated_at.replace(tzinfo=None)
            if start is not None and updated_at < start.replace(tzinfo=None):
                continue
            if end is not None and updated_at > end.replace(tzinfo=None):
                continue

            # Build contact name
            name_parts = []
            if contact.properties.get("firstname"):
                name_parts.append(contact.properties["firstname"])
            if contact.properties.get("lastname"):
                name_parts.append(contact.properties["lastname"])

            if name_parts:
                title = " ".join(name_parts)
            elif contact.properties.get("email"):
                # Use email as fallback if no first/last name
                title = contact.properties["email"]
            else:
                title = f"Contact {contact.id}"

            link = self._get_object_url("contacts", contact.id)

            # Build main content
            content_parts = [f"Contact: {title}"]
            if contact.properties.get("email"):
                content_parts.append(f"Email: {contact.properties['email']}")
            if contact.properties.get("company"):
                content_parts.append(f"Company: {contact.properties['company']}")
            if contact.properties.get("jobtitle"):
                content_parts.append(f"Job Title: {contact.properties['jobtitle']}")
            if contact.properties.get("phone"):
                content_parts.append(f"Phone: {contact.properties['phone']}")
            if contact.properties.get("city") and contact.properties.get("state"):
                content_parts.append(
                    f"Location: {contact.properties['city']}, {contact.properties['state']}"
                )

            content_text = "\n".join(content_parts)

            # Main contact section
            sections = [TextSection(link=link, text=content_text)]

            # Metadata with parent object IDs
            metadata: dict[str, str | list[str]] = {
                "contact_id": contact.id,
                "object_type": "contact",
            }

            if contact.properties.get("email"):
                metadata["email"] = contact.properties["email"]
            if contact.properties.get("company"):
                metadata["company"] = contact.properties["company"]
            if contact.properties.get("jobtitle"):
                metadata["job_title"] = contact.properties["jobtitle"]

            # Add associated objects as sections
            associated_company_ids = []
            associated_deal_ids = []
            associated_ticket_ids = []

            # Get associated companies
            associated_companies = self._get_associated_objects(
                api_client, contact.id, "contacts", "companies"
            )
            for company in associated_companies:
                sections.append(self._create_object_section(company, "companies"))
                associated_company_ids.append(company["id"])

            # Get associated deals
            associated_deals = self._get_associated_objects(
                api_client, contact.id, "contacts", "deals"
            )
            for deal in associated_deals:
                sections.append(self._create_object_section(deal, "deals"))
                associated_deal_ids.append(deal["id"])

            # Get associated tickets
            associated_tickets = self._get_associated_objects(
                api_client, contact.id, "contacts", "tickets"
            )
            for ticket in associated_tickets:
                sections.append(self._create_object_section(ticket, "tickets"))
                associated_ticket_ids.append(ticket["id"])

            # Get associated notes
            associated_notes = self._get_associated_notes(
                api_client, contact.id, "contacts"
            )
            for note in associated_notes:
                sections.append(self._create_object_section(note, "notes"))

            # Add association IDs to metadata
            if associated_company_ids:
                metadata["associated_company_ids"] = associated_company_ids
            if associated_deal_ids:
                metadata["associated_deal_ids"] = associated_deal_ids
            if associated_ticket_ids:
                metadata["associated_ticket_ids"] = associated_ticket_ids

            doc_batch.append(
                Document(
                    id=f"hubspot_contact_{contact.id}",
                    sections=cast(list[TextSection | ImageSection], sections),
                    source=DocumentSource.HUBSPOT,
                    semantic_identifier=title,
                    doc_updated_at=contact.updated_at.replace(tzinfo=timezone.utc),
                    metadata=metadata,
                )
            )

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all HubSpot objects (tickets, companies, deals, contacts)"""
        # Process each object type based on configuration
        if "tickets" in self.object_types:
            yield from self._process_tickets()
        if "companies" in self.object_types:
            yield from self._process_companies()
        if "deals" in self.object_types:
            yield from self._process_deals()
        if "contacts" in self.object_types:
            yield from self._process_contacts()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)

        # Process each object type with time filtering based on configuration
        if "tickets" in self.object_types:
            yield from self._process_tickets(start_datetime, end_datetime)
        if "companies" in self.object_types:
            yield from self._process_companies(start_datetime, end_datetime)
        if "deals" in self.object_types:
            yield from self._process_deals(start_datetime, end_datetime)
        if "contacts" in self.object_types:
            yield from self._process_contacts(start_datetime, end_datetime)


if __name__ == "__main__":
    import os

    connector = HubSpotConnector()
    connector.load_credentials(
        {"hubspot_access_token": os.environ["HUBSPOT_ACCESS_TOKEN"]}
    )
    # Run the first example
    document_batches = connector.load_from_state()
    first_batch = next(document_batches)
    for doc in first_batch:
        print(doc.model_dump_json(indent=2))
