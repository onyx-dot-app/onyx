import re
import time
from collections.abc import Callable, Generator, Iterator
from datetime import datetime, timezone
from itertools import islice
from typing import Any, cast

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import (
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.hubspot.config import HUBSPOT_OBJECT_SPECS, HubSpotObjectType
from onyx.connectors.hubspot.models import (
    HubSpotDocumentParts,
    HubSpotRecord,
)
from onyx.connectors.hubspot.permissions import HubSpotPermissionReader
from onyx.connectors.hubspot.source_operations import (
    HUBSPOT_PAGE_SIZE,
    NOTES_OBJECT_TYPE,
    PERMITTED_USERS_BATCH_SIZE,
    HubSpotApiError,
    HubSpotSourceOperations,
    iter_pages,
)
from onyx.connectors.interfaces import (
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger

HUBSPOT_BASE_URL = "https://app.hubspot.com"

AVAILABLE_OBJECT_TYPES = {object_type.value for object_type in HubSpotObjectType}

# HubSpot Search API rejects cursors beyond this offset.
HUBSPOT_SEARCH_LIMIT = 10_000
_SEARCH_PAGES = HUBSPOT_SEARCH_LIMIT // HUBSPOT_PAGE_SIZE + 1
# Ten million records, far past any portal, so a stuck cursor cannot spin.
_MAX_LISTING_PAGES = 100_000
_MAX_ASSOCIATION_PAGES = 1_000

INDEXED_PROPERTIES: dict[HubSpotObjectType, list[str]] = {
    HubSpotObjectType.TICKETS: [
        "subject",
        "content",
        "hs_ticket_priority",
        "createdate",
        "hs_lastmodifieddate",
    ],
    HubSpotObjectType.COMPANIES: [
        "name",
        "domain",
        "industry",
        "city",
        "state",
        "description",
        "createdate",
        "hs_lastmodifieddate",
    ],
    HubSpotObjectType.DEALS: [
        "dealname",
        "amount",
        "dealstage",
        "closedate",
        "pipeline",
        "description",
        "createdate",
        "hs_lastmodifieddate",
    ],
    HubSpotObjectType.CONTACTS: [
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
}
# Properties read for a record folded into another record's document.
ASSOC_PROPERTIES: dict[str, list[str]] = {
    HubSpotObjectType.CONTACTS.value: [
        "firstname",
        "lastname",
        "email",
        "company",
        "jobtitle",
    ],
    HubSpotObjectType.COMPANIES.value: ["name", "domain", "industry", "city", "state"],
    HubSpotObjectType.DEALS.value: [
        "dealname",
        "amount",
        "dealstage",
        "closedate",
        "pipeline",
    ],
    HubSpotObjectType.TICKETS.value: ["subject", "content", "hs_ticket_priority"],
    NOTES_OBJECT_TYPE: [
        "hs_note_body",
        "hs_timestamp",
        "hs_created_by",
        "hubspot_owner_id",
    ],
}
# The types each document folds in as sections, in section order.
ASSOCIATED_TYPES: dict[HubSpotObjectType, list[HubSpotObjectType]] = {
    HubSpotObjectType.TICKETS: [
        HubSpotObjectType.CONTACTS,
        HubSpotObjectType.COMPANIES,
        HubSpotObjectType.DEALS,
    ],
    HubSpotObjectType.COMPANIES: [
        HubSpotObjectType.CONTACTS,
        HubSpotObjectType.DEALS,
        HubSpotObjectType.TICKETS,
    ],
    HubSpotObjectType.DEALS: [
        HubSpotObjectType.CONTACTS,
        HubSpotObjectType.COMPANIES,
        HubSpotObjectType.TICKETS,
    ],
    HubSpotObjectType.CONTACTS: [
        HubSpotObjectType.COMPANIES,
        HubSpotObjectType.DEALS,
        HubSpotObjectType.TICKETS,
    ],
}
# The cheapest property to request. Every record carries it.
HS_OBJECT_ID_PROPERTY = "hs_object_id"
_SLIM_BATCH_SIZE = 1000
_SLIM_DOC_SYNC_LABEL = "hubspot_slim_doc_sync"

_Properties = dict[str, str | None]

logger = setup_logger()


def hubspot_document_id(object_type: HubSpotObjectType, object_id: str) -> str:
    return f"hubspot_{HUBSPOT_OBJECT_SPECS[object_type].document_noun}_{object_id}"


def _utc(timestamp: SecondsSinceUnixEpoch | None) -> datetime | None:
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if timestamp is not None
        else None
    )


def _probe_scope(call: Callable[[], object]) -> None:
    try:
        call()
    except HubSpotApiError as e:
        if e.status != 403:
            raise
        raise InsufficientPermissionsError(
            f"HubSpot refused the {e.operation}. Permission sync needs the private "
            "app to read users (settings.users.read) and the viewers of records."
        ) from e


def _clean_html(html_content: str) -> str:
    """Strips tags and the common entities, which is enough for note bodies."""
    clean_text = re.sub(r"<[^>]+>", "", html_content)
    for entity, char in (
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
    ):
        clean_text = clean_text.replace(entity, char)
    return " ".join(clean_text.split()).strip()


def _labeled(properties: _Properties, fields: list[tuple[str, str]]) -> list[str]:
    return [
        f"{label}: {value}" for label, key in fields if (value := properties.get(key))
    ]


def _location(properties: _Properties) -> list[str]:
    city, state = properties.get("city"), properties.get("state")
    return [f"Location: {city}, {state}"] if city and state else []


def _amount(properties: _Properties) -> list[str]:
    amount: str | None = properties.get("amount")
    return [f"Amount: ${amount}"] if amount else []


def _contact_name(properties: _Properties, fallback: str) -> str:
    name: str = " ".join(
        part
        for part in (properties.get("firstname"), properties.get("lastname"))
        if part
    )
    return name or properties.get("email") or fallback


def _ticket_parts(record: HubSpotRecord) -> HubSpotDocumentParts:
    properties: _Properties = record.properties
    return HubSpotDocumentParts(
        title=properties.get("subject") or f"Ticket {record.id}",
        text=properties.get("content") or "",
        metadata={
            "object_type": "ticket",
            **_metadata(properties, [("priority", "hs_ticket_priority")]),
        },
    )


def _company_parts(record: HubSpotRecord) -> HubSpotDocumentParts:
    properties: _Properties = record.properties
    title: str = properties.get("name") or f"Company {record.id}"
    lines: list[str] = [
        f"Company: {title}",
        *_labeled(properties, [("Domain", "domain"), ("Industry", "industry")]),
        *_location(properties),
        *_labeled(properties, [("Description", "description")]),
    ]
    return HubSpotDocumentParts(
        title=title,
        text="\n".join(lines),
        metadata={
            "company_id": record.id,
            "object_type": "company",
            **_metadata(properties, [("industry", "industry"), ("domain", "domain")]),
        },
    )


def _deal_parts(record: HubSpotRecord) -> HubSpotDocumentParts:
    properties: _Properties = record.properties
    title: str = properties.get("dealname") or f"Deal {record.id}"
    lines: list[str] = [
        f"Deal: {title}",
        *_amount(properties),
        *_labeled(
            properties,
            [
                ("Stage", "dealstage"),
                ("Close Date", "closedate"),
                ("Pipeline", "pipeline"),
                ("Description", "description"),
            ],
        ),
    ]
    return HubSpotDocumentParts(
        title=title,
        text="\n".join(lines),
        metadata={
            "deal_id": record.id,
            "object_type": "deal",
            **_metadata(
                properties,
                [
                    ("deal_stage", "dealstage"),
                    ("pipeline", "pipeline"),
                    ("amount", "amount"),
                ],
            ),
        },
    )


def _contact_parts(record: HubSpotRecord) -> HubSpotDocumentParts:
    properties: _Properties = record.properties
    title: str = _contact_name(properties, f"Contact {record.id}")
    lines: list[str] = [
        f"Contact: {title}",
        *_labeled(
            properties,
            [
                ("Email", "email"),
                ("Company", "company"),
                ("Job Title", "jobtitle"),
                ("Phone", "phone"),
            ],
        ),
        *_location(properties),
    ]
    return HubSpotDocumentParts(
        title=title,
        text="\n".join(lines),
        metadata={
            "contact_id": record.id,
            "object_type": "contact",
            **_metadata(
                properties,
                [("email", "email"), ("company", "company"), ("job_title", "jobtitle")],
            ),
        },
    )


def _metadata(properties: _Properties, fields: list[tuple[str, str]]) -> dict[str, str]:
    return {name: value for name, key in fields if (value := properties.get(key))}


_DOCUMENT_PARTS: dict[
    HubSpotObjectType, Callable[[HubSpotRecord], HubSpotDocumentParts]
] = {
    HubSpotObjectType.TICKETS: _ticket_parts,
    HubSpotObjectType.COMPANIES: _company_parts,
    HubSpotObjectType.DEALS: _deal_parts,
    HubSpotObjectType.CONTACTS: _contact_parts,
}


def _section_lines(variant: str, properties: _Properties) -> list[str]:
    """The text of a record folded into another record's document."""
    if variant == HubSpotObjectType.CONTACTS:
        return [
            f"Contact: {_contact_name(properties, 'Unknown Contact')}",
            *_labeled(
                properties,
                [("Email", "email"), ("Company", "company"), ("Job Title", "jobtitle")],
            ),
        ]
    if variant == HubSpotObjectType.COMPANIES:
        return [
            f"Company: {properties.get('name') or 'Unknown Company'}",
            *_labeled(properties, [("Domain", "domain"), ("Industry", "industry")]),
            *_location(properties),
        ]
    if variant == HubSpotObjectType.DEALS:
        return [
            f"Deal: {properties.get('dealname') or 'Unknown Deal'}",
            *_amount(properties),
            *_labeled(
                properties,
                [
                    ("Stage", "dealstage"),
                    ("Close Date", "closedate"),
                    ("Pipeline", "pipeline"),
                ],
            ),
        ]
    if variant == HubSpotObjectType.TICKETS:
        return [
            f"Ticket: {properties.get('subject') or 'Unknown Ticket'}",
            *_labeled(
                properties, [("Content", "content"), ("Priority", "hs_ticket_priority")]
            ),
        ]
    return [
        f"Note: {_clean_html(properties.get('hs_note_body') or '')}",
        *_labeled(properties, [("Created", "hs_timestamp")]),
    ]


class HubSpotConnector(
    LoadConnector,
    PollConnector,
    SlimConnector,
    SlimConnectorWithPermSync,
    CredentialsConnector,
):
    # The slim listings filter on the same modified date as poll_source.
    slim_listing_honors_indexing_start = True

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        object_types: list[str] | None = None,
    ) -> None:
        self.batch_size = batch_size
        self._ops: HubSpotSourceOperations | None = None
        self._portal_id: str | None = None

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
    def ops(self) -> HubSpotSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("HubSpot")
        return self._ops

    @property
    def portal_id(self) -> str:
        """Fetched once per credential, on first use."""
        if self._portal_id is None:
            self._portal_id = self.ops.get_portal_id()
        return self._portal_id

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.set_credentials_provider(
            OnyxStaticCredentialsProvider(
                None, DocumentSource.HUBSPOT.value, credentials
            )
        )
        return None

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = HubSpotSourceOperations(credentials_provider=credentials_provider)
        self._portal_id = None

    def validate_connector_settings(self) -> None:
        """Nothing else calls HubSpot at creation, so a dead token is refused here."""
        try:
            self._portal_id = self.ops.get_portal_id()
        except HubSpotApiError as e:
            if e.status in (401, 403):
                raise CredentialInvalidError(
                    f"HubSpot refused the {e.operation}. Check the access token."
                ) from e
            raise UnexpectedValidationError(str(e)) from e

    def _configured_object_types(self) -> list[HubSpotObjectType]:
        return [
            object_type
            for object_type in HubSpotObjectType
            if object_type.value in self.object_types
        ]

    def _batch_read(
        self, variant: str, ids: list[str], properties: list[str]
    ) -> list[HubSpotRecord]:
        """Reads with one retry and logs the dropped ids when both attempts fail."""
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                return self.ops.read_records(
                    variant=variant, ids=ids, properties=properties
                )
            except Exception as e:
                last_exc = e
                if attempt == 0:
                    logger.warning(
                        "Batch fetch of %s %s failed, retrying: %s",
                        len(ids),
                        variant,
                        e,
                    )
                    time.sleep(1)
        logger.warning(
            "Failed to batch-fetch %s %s %s after retry: %s",
            len(ids),
            variant,
            ids,
            last_exc,
        )
        return []

    def _list_all_records(
        self,
        object_type: HubSpotObjectType,
        properties: list[str],
        associations: list[HubSpotObjectType] | None = None,
    ) -> Iterator[HubSpotRecord]:
        return iter_pages(
            lambda after: self.ops.list_records(
                variant=object_type,
                properties=properties,
                associations=associations,
                after=after,
            ),
            _MAX_LISTING_PAGES,
        )

    def _list_association_ids(
        self,
        object_type: HubSpotObjectType,
        object_id: str,
        to_object_type: str,
    ) -> list[str]:
        """Deduplicated, since HubSpot returns one entry per association label."""
        ids = iter_pages(
            lambda after: self.ops.list_associations(
                object_type=object_type,
                object_id=object_id,
                to_object_type=to_object_type,
                after=after,
            ),
            _MAX_ASSOCIATION_PAGES,
        )
        return list(dict.fromkeys(ids))

    def _search_time_range(
        self,
        object_type: HubSpotObjectType,
        properties: list[str],
        start: datetime,
        end: datetime | None,
        incomplete_is_error: bool = False,
    ) -> Generator[HubSpotRecord, None, None]:
        """Records modified in [start, end], oldest first. Past HubSpot's
        10,000-result cap the search restarts from the last modified timestamp,
        so records sharing that timestamp may repeat. A cap the search cannot
        pass ends the listing early, or raises when incomplete_is_error."""
        modified_date_prop = HUBSPOT_OBJECT_SPECS[object_type].modified_date_property
        pages = iter_pages(
            lambda after: self.ops.search_records(
                variant=object_type,
                properties=properties,
                modified_after=start,
                modified_before=end,
                after=after,
            ),
            _SEARCH_PAGES,
        )
        results = list(islice(pages, HUBSPOT_SEARCH_LIMIT))

        yield from results

        if len(results) < HUBSPOT_SEARCH_LIMIT:
            return

        def incomplete(reason: str) -> None:
            message = (
                f"HubSpot search limit reached but {reason}. Records after the "
                f"{HUBSPOT_SEARCH_LIMIT}th may be missing."
            )
            if incomplete_is_error:
                raise RuntimeError(message)
            logger.error(message)

        # Hit the cap, so continue from the last seen modified timestamp.
        last_ts_ms = results[-1].properties.get(modified_date_prop)
        if last_ts_ms is None:
            incomplete("the last modified timestamp is unavailable")
            return

        try:
            # Search API returns ISO 8601 strings; filter values use ms epoch.
            next_start = datetime.fromisoformat(last_ts_ms)
        except ValueError:
            try:
                next_start = datetime.fromtimestamp(
                    int(last_ts_ms) / 1000, tz=timezone.utc
                )
            except ValueError:
                incomplete(
                    f"the last modified timestamp has unrecognized format ({last_ts_ms!r})"
                )
                return
        if next_start <= start:
            incomplete("the timestamp did not advance")
            return

        yield from self._search_time_range(
            object_type,
            properties,
            next_start,
            end,
            incomplete_is_error,
        )

    def _iter_records(
        self,
        object_type: HubSpotObjectType,
        properties: list[str],
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[HubSpotRecord]:
        """A full listing carries associations inline. A search cannot, so a
        poll window pays one associations call per type per record."""
        if start is None and end is None:
            return self._list_all_records(
                object_type, properties, ASSOCIATED_TYPES[object_type]
            )
        return self._search_time_range(
            object_type,
            properties,
            start or datetime.min.replace(tzinfo=timezone.utc),
            end or datetime.max.replace(tzinfo=timezone.utc),
        )

    def _record_url(self, object_type: HubSpotObjectType, object_id: str) -> str:
        type_id = HUBSPOT_OBJECT_SPECS[object_type].type_id
        return (
            f"{HUBSPOT_BASE_URL}/contacts/{self.portal_id}/record/{type_id}/{object_id}"
        )

    def _section_url(self, variant: str, object_id: str) -> str:
        if variant == NOTES_OBJECT_TYPE:
            return (
                f"{HUBSPOT_BASE_URL}/contacts/{self.portal_id}/objects/0-4/{object_id}"
            )
        return self._record_url(HubSpotObjectType(variant), object_id)

    def _extract_inline_association_ids(
        self, record: HubSpotRecord, assoc_type: HubSpotObjectType
    ) -> list[str] | None:
        """Inline association ids for one type. None when HubSpot sent no inline
        list or paged it, so the caller reads the v4 API. [] when the type has none."""
        if record.associations is None:
            return None
        inline = record.associations.get(assoc_type)
        if inline is None:
            return []
        if inline.has_more:
            return None
        return inline.ids

    def _get_associated_objects(
        self,
        object_type: HubSpotObjectType,
        record: HubSpotRecord,
        to_object_type: HubSpotObjectType,
    ) -> list[HubSpotRecord]:
        try:
            object_ids = self._extract_inline_association_ids(record, to_object_type)
            if object_ids is None:
                object_ids = self._list_association_ids(
                    object_type, record.id, to_object_type.value
                )
            associated_objects: list[HubSpotRecord] = []
            for chunk in batch_generator(object_ids, HUBSPOT_PAGE_SIZE):
                associated_objects.extend(
                    self._batch_read(
                        to_object_type.value,
                        chunk,
                        ASSOC_PROPERTIES[to_object_type.value],
                    )
                )
            return associated_objects
        except Exception as e:
            logger.warning(
                "Failed to get associations from %s to %s: %s",
                object_type,
                to_object_type,
                e,
            )
            return []

    def _get_associated_notes(
        self, object_type: HubSpotObjectType, object_id: str
    ) -> list[HubSpotRecord]:
        try:
            note_ids = self._list_association_ids(
                object_type, object_id, NOTES_OBJECT_TYPE
            )
            associated_notes: list[HubSpotRecord] = []
            for chunk in batch_generator(note_ids, HUBSPOT_PAGE_SIZE):
                associated_notes.extend(
                    self._batch_read(
                        NOTES_OBJECT_TYPE, chunk, ASSOC_PROPERTIES[NOTES_OBJECT_TYPE]
                    )
                )
            return associated_notes
        except Exception as e:
            logger.warning(
                "Failed to get notes for %s %s: %s", object_type, object_id, e
            )
            return []

    def _create_object_section(
        self, record: HubSpotRecord, variant: str
    ) -> TextSection:
        return TextSection(
            link=self._section_url(variant, record.id),
            text="\n".join(_section_lines(variant, record.properties)),
        )

    def _add_associations(
        self,
        object_type: HubSpotObjectType,
        record: HubSpotRecord,
        sections: list[TextSection],
        metadata: dict[str, str | list[str]],
    ) -> None:
        """Note ids stay out of the metadata, only record ids are listed."""
        for to_object_type in ASSOCIATED_TYPES[object_type]:
            associated = self._get_associated_objects(
                object_type, record, to_object_type
            )
            sections.extend(
                self._create_object_section(obj, to_object_type.value)
                for obj in associated
            )
            if associated:
                noun = HUBSPOT_OBJECT_SPECS[to_object_type].document_noun
                metadata[f"associated_{noun}_ids"] = [obj.id for obj in associated]
        sections.extend(
            self._create_object_section(note, NOTES_OBJECT_TYPE)
            for note in self._get_associated_notes(object_type, record.id)
        )

    def _documents(
        self,
        object_type: HubSpotObjectType,
        start: datetime | None,
        end: datetime | None,
    ) -> Generator[Document | HierarchyNode, None, None]:
        spec = HUBSPOT_OBJECT_SPECS[object_type]
        for record in self._iter_records(
            object_type, INDEXED_PROPERTIES[object_type], start, end
        ):
            parts: HubSpotDocumentParts = _DOCUMENT_PARTS[object_type](record)
            sections: list[TextSection] = [
                TextSection(
                    link=self._record_url(object_type, record.id), text=parts.text
                )
            ]
            metadata: dict[str, str | list[str]] = dict(parts.metadata)
            self._add_associations(object_type, record, sections, metadata)
            yield Document(
                id=hubspot_document_id(object_type, record.id),
                sections=cast(list[TextSection | ImageSection], sections),
                source=DocumentSource.HUBSPOT,
                semantic_identifier=parts.title,
                doc_created_at=record.created_at,
                doc_updated_at=record.updated_at,
                metadata=metadata,
                doc_metadata={
                    "hierarchy": {
                        "source_path": [object_type.value.capitalize()],
                        "object_type": spec.document_noun,
                        "object_id": record.id,
                    }
                },
            )

    def _process(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> GenerateDocumentsOutput:
        for object_type in self._configured_object_types():
            yield from batch_generator(
                self._documents(object_type, start, end), self.batch_size
            )

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        # Epoch 0 means no prior successful sync, so list everything with inline
        # associations instead of searching.
        if start == 0:
            return self._process()
        return self._process(_utc(start), _utc(end))

    def _iter_record_ids(
        self,
        object_type: HubSpotObjectType,
        start: datetime | None,
        end: datetime | None,
    ) -> Generator[str, None, None]:
        if start is None:
            # Pruning and doc sync pass a start at most, so this is the full listing.
            records = self._list_all_records(object_type, [HS_OBJECT_ID_PROPERTY])
        else:
            # The search walk reads the modified date to pass the 10,000-result cap.
            # A partial listing would revoke access or prune live records.
            modified_date_property = HUBSPOT_OBJECT_SPECS[
                object_type
            ].modified_date_property
            records = self._search_time_range(
                object_type,
                [HS_OBJECT_ID_PROPERTY, modified_date_property],
                start,
                end,
                incomplete_is_error=True,
            )
        for record in records:
            yield record.id

    def _permission_reader(self) -> HubSpotPermissionReader:
        return HubSpotPermissionReader(self.ops, self.portal_id)

    def _iter_slim_docs(
        self, start: datetime | None, end: datetime | None
    ) -> Generator[SlimDocument | HierarchyNode, None, None]:
        for object_type in self._configured_object_types():
            for record_id in self._iter_record_ids(object_type, start, end):
                yield SlimDocument(id=hubspot_document_id(object_type, record_id))

    def _iter_slim_docs_with_access(
        self,
        start: datetime | None,
        end: datetime | None,
        callback: IndexingHeartbeatInterface | None,
    ) -> Generator[SlimDocument | HierarchyNode, None, None]:
        reader = self._permission_reader()
        for object_type in self._configured_object_types():
            record_ids = self._iter_record_ids(object_type, start, end)
            for chunk in batch_generator(record_ids, PERMITTED_USERS_BATCH_SIZE):
                # Every chunk is a remote call, so the sync lock is refreshed here
                # and not only once per yielded batch of _SLIM_BATCH_SIZE.
                if callback:
                    if callback.should_stop():
                        raise RuntimeError(
                            f"{_SLIM_DOC_SYNC_LABEL}: Stop signal detected"
                        )
                    callback.progress(_SLIM_DOC_SYNC_LABEL, 1)
                viewers = reader.viewers(object_type, chunk)
                for record_id in chunk:
                    yield SlimDocument(
                        id=hubspot_document_id(object_type, record_id),
                        external_access=reader.access_for(viewers[record_id]),
                    )

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        yield from batch_generator(
            self._iter_slim_docs(_utc(start), _utc(end)), _SLIM_BATCH_SIZE
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every configured record with the emails of the users HubSpot lets view it."""
        yield from batch_generator(
            self._iter_slim_docs_with_access(_utc(start), _utc(end), callback),
            _SLIM_BATCH_SIZE,
        )

    def _sample_record(self) -> tuple[HubSpotObjectType, str] | None:
        for object_type in self._configured_object_types():
            page = self.ops.list_records(
                variant=object_type, properties=[HS_OBJECT_ID_PROPERTY], limit=1
            )
            if page.items:
                return object_type, page.items[0].id
        return None

    def probe_permission_sync_scopes(self) -> None:
        """A 403 here is a missing private-app scope. Failing creation with the
        refused operation named beats a sync that never succeeds while every
        record stays hidden."""
        _probe_scope(lambda: self.ops.list_users(limit=1))
        sample = self._sample_record()
        if sample is None:
            logger.warning(
                "HubSpot has no records yet, so the viewer lookup stays "
                "unchecked until one exists"
            )
            return
        object_type, record_id = sample
        reader = self._permission_reader()
        _probe_scope(lambda: reader.viewers(object_type, [record_id]))


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
