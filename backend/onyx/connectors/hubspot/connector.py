import re
import time
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import TypeVar

import requests
from hubspot import HubSpot
from hubspot.crm.companies.models import (
    BatchReadInputSimplePublicObjectId as CompaniesBatchReadInput,
)
from hubspot.crm.companies.models import SimplePublicObjectId as CompanyObjectId
from hubspot.crm.contacts.models import (
    BatchReadInputSimplePublicObjectId as ContactsBatchReadInput,
)
from hubspot.crm.contacts.models import Filter
from hubspot.crm.contacts.models import FilterGroup
from hubspot.crm.contacts.models import PublicObjectSearchRequest
from hubspot.crm.contacts.models import SimplePublicObjectId as ContactObjectId
from hubspot.crm.deals.models import (
    BatchReadInputSimplePublicObjectId as DealsBatchReadInput,
)
from hubspot.crm.deals.models import SimplePublicObjectId as DealObjectId
from hubspot.crm.objects.notes.models import (
    BatchReadInputSimplePublicObjectId as NotesBatchReadInput,
)
from hubspot.crm.objects.notes.models import SimplePublicObjectId as NoteObjectId
from hubspot.crm.tickets.models import (
    BatchReadInputSimplePublicObjectId as TicketsBatchReadInput,
)
from hubspot.crm.tickets.models import SimplePublicObjectId as TicketObjectId

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.hubspot.rate_limit import HubSpotRateLimiter
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

HUBSPOT_BASE_URL = "https://app.hubspot.com"
HUBSPOT_API_URL = "https://api.hubapi.com/integrations/v1/me"

AVAILABLE_OBJECT_TYPES = {"tickets", "companies", "deals", "contacts"}

HUBSPOT_PAGE_SIZE = 100
# HubSpot Search API rejects cursors beyond this offset.
HUBSPOT_SEARCH_LIMIT = 10_000

ASSOC_CONTACT_PROPERTIES = ["firstname", "lastname", "email", "company", "jobtitle"]
ASSOC_COMPANY_PROPERTIES = ["name", "domain", "industry", "city", "state"]
ASSOC_DEAL_PROPERTIES = ["dealname", "amount", "dealstage", "closedate", "pipeline"]
ASSOC_TICKET_PROPERTIES = ["subject", "content", "hs_ticket_priority"]
ASSOC_NOTE_PROPERTIES = [
    "hs_note_body",
    "hs_timestamp",
    "hs_created_by",
    "hubspot_owner_id",
]


_T = TypeVar("_T")


def _chunked(items: list[_T], size: int) -> Generator[list[_T], None, None]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


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

    def _batch_read(
        self,
        batch_fn: Callable[..., Any],
        batch_input: Any,
        object_type: str,
        chunk: list[Any],
    ) -> list[dict[str, Any]]:
        """Call batch_fn with one retry; logs dropped IDs if both attempts fail."""
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = self._call_hubspot(batch_fn, batch_input)
                return [obj.to_dict() for obj in (resp.results or [])]
            except Exception as e:
                last_exc = e
                if attempt == 0:
                    logger.warning(
                        f"Batch fetch of {len(chunk)} {object_type} failed, retrying: {e}"
                    )
                    time.sleep(1)
        logger.warning(
            f"Failed to batch-fetch {len(chunk)} {object_type} {chunk} after retry: {last_exc}"
        )
        return []

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

    def _build_time_filter_group(
        self,
        start: datetime | None,
        end: datetime | None,
        property_name: str,
    ) -> FilterGroup:
        filters: list[Filter] = []
        if start is not None:
            filters.append(
                Filter(
                    property_name=property_name,
                    operator="GTE",
                    value=str(int(start.timestamp() * 1000)),
                )
            )
        if end is not None:
            filters.append(
                Filter(
                    property_name=property_name,
                    operator="LTE",
                    value=str(int(end.timestamp() * 1000)),
                )
            )
        return FilterGroup(filters=filters)

    def _search_paginated_results(
        self,
        search_fn: Callable[..., Any],
        properties: list[str],
        filter_group: FilterGroup,
        sorts: list[str] | None = None,
    ) -> Generator[Any, None, None]:
        after: str | None = None
        while True:
            request = PublicObjectSearchRequest(
                filter_groups=[filter_group],
                limit=HUBSPOT_PAGE_SIZE,
                properties=properties,
                after=after,
                sorts=sorts,
            )
            page = self._call_hubspot(search_fn, public_object_search_request=request)
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

    def _search_time_range(
        self,
        search_fn: Callable[..., Any],
        properties: list[str],
        start: datetime,
        end: datetime,
        modified_date_prop: str,
    ) -> Generator[Any, None, None]:
        """Search [start, end] sorted by modified date ASC.

        If results hit the 10,000-record hard cap, yield all fetched results
        and continue from the last seen modified timestamp. Documents sharing
        that exact timestamp may be yielded twice (acceptable — re-indexing is
        idempotent).

        Note: PublicObjectSearchRequest does not support an `associations`
        parameter, so objects returned here will not have inline association
        data. _extract_inline_association_ids will return None for each object,
        falling back to a v4 associations API call per association type per
        record (O(N×M) extra calls). This is acceptable for poll windows, which
        are small by design (typically tens to low hundreds of changed objects
        per 15-second window).
        """
        filter_group = self._build_time_filter_group(start, end, modified_date_prop)
        results: list[Any] = []
        for result in self._search_paginated_results(
            search_fn, properties, filter_group, sorts=[modified_date_prop]
        ):
            results.append(result)
            if len(results) >= HUBSPOT_SEARCH_LIMIT:
                break

        yield from results

        if len(results) < HUBSPOT_SEARCH_LIMIT:
            return

        # Hit the cap — continue from the last seen modified timestamp.
        last_ts_ms = (results[-1].properties or {}).get(modified_date_prop)
        if last_ts_ms is None:
            logger.error(
                "HubSpot search limit reached but last modified timestamp is "
                "unavailable; records after the 10,000th may be missing."
            )
            return

        try:
            # Search API returns ISO 8601 strings; filter values use ms epoch.
            next_start = datetime.fromisoformat(last_ts_ms.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            try:
                next_start = datetime.fromtimestamp(
                    int(last_ts_ms) / 1000, tz=timezone.utc
                )
            except (ValueError, TypeError):
                logger.error(
                    f"HubSpot search limit reached but last modified timestamp "
                    f"has unrecognized format ({last_ts_ms!r}); records after "
                    "the 10,000th may be missing."
                )
                return
        if next_start <= start:
            logger.error(
                "HubSpot search limit reached but timestamp did not advance; "
                "records after the 10,000th may be missing."
            )
            return

        yield from self._search_time_range(
            search_fn, properties, next_start, end, modified_date_prop
        )

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

        response = requests.get(
            HUBSPOT_API_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
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

    def _extract_inline_association_ids(
        self,
        obj: Any,
        assoc_type: str,
    ) -> list[str] | None:
        """Extract association IDs already returned inline by get_page.

        Returns None when the inline data is incomplete (overflow) or when
        associations is not a dict (not fetched or unexpected SDK type), so the
        caller falls back to a dedicated v4 associations API call instead.
        Returns [] when the type simply has no associations.
        """
        associations = getattr(obj, "associations", None)
        if not isinstance(associations, dict):
            return None
        assoc_collection = associations.get(assoc_type)
        if assoc_collection is None:
            return []
        if assoc_collection.paging and assoc_collection.paging.next:
            return None
        return list(dict.fromkeys(r.id for r in (assoc_collection.results or [])))

    def _get_associated_objects(
        self,
        api_client: HubSpot,
        object_id: str,
        from_object_type: str,
        to_object_type: str,
        inline_association_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get associated objects for a given object"""
        try:
            if inline_association_ids is not None:
                object_ids = inline_association_ids
            else:
                associations_iter = self._paginated_results(
                    api_client.crm.associations.v4.basic_api.get_page,
                    object_type=from_object_type,
                    object_id=object_id,
                    to_object_type=to_object_type,
                )
                object_ids = list(
                    dict.fromkeys(
                        str(assoc.to_object_id) for assoc in associations_iter
                    )
                )

            associated_objects: list[dict[str, Any]] = []

            if to_object_type == "contacts":
                for chunk in _chunked(object_ids, HUBSPOT_PAGE_SIZE):
                    associated_objects.extend(
                        self._batch_read(
                            api_client.crm.contacts.batch_api.read,
                            ContactsBatchReadInput(
                                properties=ASSOC_CONTACT_PROPERTIES,
                                inputs=[ContactObjectId(id=i) for i in chunk],
                            ),
                            "contacts",
                            chunk,
                        )
                    )

            elif to_object_type == "companies":
                for chunk in _chunked(object_ids, HUBSPOT_PAGE_SIZE):
                    associated_objects.extend(
                        self._batch_read(
                            api_client.crm.companies.batch_api.read,
                            CompaniesBatchReadInput(
                                properties=ASSOC_COMPANY_PROPERTIES,
                                inputs=[CompanyObjectId(id=i) for i in chunk],
                            ),
                            "companies",
                            chunk,
                        )
                    )

            elif to_object_type == "deals":
                for chunk in _chunked(object_ids, HUBSPOT_PAGE_SIZE):
                    associated_objects.extend(
                        self._batch_read(
                            api_client.crm.deals.batch_api.read,
                            DealsBatchReadInput(
                                properties=ASSOC_DEAL_PROPERTIES,
                                inputs=[DealObjectId(id=i) for i in chunk],
                            ),
                            "deals",
                            chunk,
                        )
                    )

            elif to_object_type == "tickets":
                for chunk in _chunked(object_ids, HUBSPOT_PAGE_SIZE):
                    associated_objects.extend(
                        self._batch_read(
                            api_client.crm.tickets.batch_api.read,
                            TicketsBatchReadInput(
                                properties=ASSOC_TICKET_PROPERTIES,
                                inputs=[TicketObjectId(id=i) for i in chunk],
                            ),
                            "tickets",
                            chunk,
                        )
                    )

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

            associated_notes: list[dict[str, Any]] = []

            for chunk in _chunked(note_ids, HUBSPOT_PAGE_SIZE):
                associated_notes.extend(
                    self._batch_read(
                        api_client.crm.objects.notes.batch_api.read,
                        NotesBatchReadInput(
                            properties=ASSOC_NOTE_PROPERTIES,
                            inputs=[NoteObjectId(id=str(nid)) for nid in chunk],
                        ),
                        "notes",
                        chunk,
                    )
                )

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

        ticket_properties = [
            "subject",
            "content",
            "hs_ticket_priority",
            "createdate",
            "hs_lastmodifieddate",
        ]

        if start is not None or end is not None:
            tickets_iter = self._search_time_range(
                api_client.crm.tickets.search_api.do_search,
                ticket_properties,
                start or datetime.min.replace(tzinfo=timezone.utc),
                end or datetime.max.replace(tzinfo=timezone.utc),
                "hs_lastmodifieddate",
            )
        else:
            tickets_iter = self._paginated_results(
                api_client.crm.tickets.basic_api.get_page,
                properties=ticket_properties,
                associations=["contacts", "companies", "deals"],
            )

        doc_batch: list[Document | HierarchyNode] = []

        for ticket in tickets_iter:
            title = ticket.properties.get("subject") or f"Ticket {ticket.id}"
            link = self._get_object_url("tickets", ticket.id)
            content_text = ticket.properties.get("content") or ""

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
                api_client,
                ticket.id,
                "tickets",
                "contacts",
                inline_association_ids=self._extract_inline_association_ids(
                    ticket, "contacts"
                ),
            )
            for contact in associated_contacts:
                sections.append(self._create_object_section(contact, "contacts"))
                associated_contact_ids.append(contact["id"])

            # Get associated companies
            associated_companies = self._get_associated_objects(
                api_client,
                ticket.id,
                "tickets",
                "companies",
                inline_association_ids=self._extract_inline_association_ids(
                    ticket, "companies"
                ),
            )
            for company in associated_companies:
                sections.append(self._create_object_section(company, "companies"))
                associated_company_ids.append(company["id"])

            # Get associated deals
            associated_deals = self._get_associated_objects(
                api_client,
                ticket.id,
                "tickets",
                "deals",
                inline_association_ids=self._extract_inline_association_ids(
                    ticket, "deals"
                ),
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
                    doc_metadata={
                        "hierarchy": {
                            "source_path": ["Tickets"],
                            "object_type": "ticket",
                            "object_id": ticket.id,
                        }
                    },
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

        company_properties = [
            "name",
            "domain",
            "industry",
            "city",
            "state",
            "description",
            "createdate",
            "hs_lastmodifieddate",
        ]

        if start is not None or end is not None:
            companies_iter = self._search_time_range(
                api_client.crm.companies.search_api.do_search,
                company_properties,
                start or datetime.min.replace(tzinfo=timezone.utc),
                end or datetime.max.replace(tzinfo=timezone.utc),
                "hs_lastmodifieddate",
            )
        else:
            companies_iter = self._paginated_results(
                api_client.crm.companies.basic_api.get_page,
                properties=company_properties,
                associations=["contacts", "deals", "tickets"],
            )

        doc_batch: list[Document | HierarchyNode] = []

        for company in companies_iter:
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
                api_client,
                company.id,
                "companies",
                "contacts",
                inline_association_ids=self._extract_inline_association_ids(
                    company, "contacts"
                ),
            )
            for contact in associated_contacts:
                sections.append(self._create_object_section(contact, "contacts"))
                associated_contact_ids.append(contact["id"])

            # Get associated deals
            associated_deals = self._get_associated_objects(
                api_client,
                company.id,
                "companies",
                "deals",
                inline_association_ids=self._extract_inline_association_ids(
                    company, "deals"
                ),
            )
            for deal in associated_deals:
                sections.append(self._create_object_section(deal, "deals"))
                associated_deal_ids.append(deal["id"])

            # Get associated tickets
            associated_tickets = self._get_associated_objects(
                api_client,
                company.id,
                "companies",
                "tickets",
                inline_association_ids=self._extract_inline_association_ids(
                    company, "tickets"
                ),
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
                    doc_metadata={
                        "hierarchy": {
                            "source_path": ["Companies"],
                            "object_type": "company",
                            "object_id": company.id,
                        }
                    },
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

        deal_properties = [
            "dealname",
            "amount",
            "dealstage",
            "closedate",
            "pipeline",
            "description",
            "createdate",
            "hs_lastmodifieddate",
        ]

        if start is not None or end is not None:
            deals_iter = self._search_time_range(
                api_client.crm.deals.search_api.do_search,
                deal_properties,
                start or datetime.min.replace(tzinfo=timezone.utc),
                end or datetime.max.replace(tzinfo=timezone.utc),
                "hs_lastmodifieddate",
            )
        else:
            deals_iter = self._paginated_results(
                api_client.crm.deals.basic_api.get_page,
                properties=deal_properties,
                associations=["contacts", "companies", "tickets"],
            )

        doc_batch: list[Document | HierarchyNode] = []

        for deal in deals_iter:
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
                api_client,
                deal.id,
                "deals",
                "contacts",
                inline_association_ids=self._extract_inline_association_ids(
                    deal, "contacts"
                ),
            )
            for contact in associated_contacts:
                sections.append(self._create_object_section(contact, "contacts"))
                associated_contact_ids.append(contact["id"])

            # Get associated companies
            associated_companies = self._get_associated_objects(
                api_client,
                deal.id,
                "deals",
                "companies",
                inline_association_ids=self._extract_inline_association_ids(
                    deal, "companies"
                ),
            )
            for company in associated_companies:
                sections.append(self._create_object_section(company, "companies"))
                associated_company_ids.append(company["id"])

            # Get associated tickets
            associated_tickets = self._get_associated_objects(
                api_client,
                deal.id,
                "deals",
                "tickets",
                inline_association_ids=self._extract_inline_association_ids(
                    deal, "tickets"
                ),
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
                    doc_metadata={
                        "hierarchy": {
                            "source_path": ["Deals"],
                            "object_type": "deal",
                            "object_id": deal.id,
                        }
                    },
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

        contact_properties = [
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
        ]

        if start is not None or end is not None:
            contacts_iter = self._search_time_range(
                api_client.crm.contacts.search_api.do_search,
                contact_properties,
                start or datetime.min.replace(tzinfo=timezone.utc),
                end or datetime.max.replace(tzinfo=timezone.utc),
                "lastmodifieddate",
            )
        else:
            contacts_iter = self._paginated_results(
                api_client.crm.contacts.basic_api.get_page,
                properties=contact_properties,
                associations=["companies", "deals", "tickets"],
            )

        doc_batch: list[Document | HierarchyNode] = []

        for contact in contacts_iter:
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
                api_client,
                contact.id,
                "contacts",
                "companies",
                inline_association_ids=self._extract_inline_association_ids(
                    contact, "companies"
                ),
            )
            for company in associated_companies:
                sections.append(self._create_object_section(company, "companies"))
                associated_company_ids.append(company["id"])

            # Get associated deals
            associated_deals = self._get_associated_objects(
                api_client,
                contact.id,
                "contacts",
                "deals",
                inline_association_ids=self._extract_inline_association_ids(
                    contact, "deals"
                ),
            )
            for deal in associated_deals:
                sections.append(self._create_object_section(deal, "deals"))
                associated_deal_ids.append(deal["id"])

            # Get associated tickets
            associated_tickets = self._get_associated_objects(
                api_client,
                contact.id,
                "contacts",
                "tickets",
                inline_association_ids=self._extract_inline_association_ids(
                    contact, "tickets"
                ),
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
                    doc_metadata={
                        "hierarchy": {
                            "source_path": ["Contacts"],
                            "object_type": "contact",
                            "object_id": contact.id,
                        }
                    },
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

        # Epoch 0 means no prior successful sync — full scan using get_page with
        # inline associations (avoids O(N×M) v4 association calls on initial load).
        is_full_scan = start == 0
        effective_start = None if is_full_scan else start_datetime
        effective_end = None if is_full_scan else end_datetime

        if "tickets" in self.object_types:
            yield from self._process_tickets(effective_start, effective_end)
        if "companies" in self.object_types:
            yield from self._process_companies(effective_start, effective_end)
        if "deals" in self.object_types:
            yield from self._process_deals(effective_start, effective_end)
        if "contacts" in self.object_types:
            yield from self._process_contacts(effective_start, effective_end)


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
