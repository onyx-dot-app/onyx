import contextvars
import re
from concurrent.futures import as_completed
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Any
from typing import cast

import requests
from pyairtable import Api as AirtableApi
from pyairtable.api.types import RecordDict
from pyairtable.models.schema import TableSchema
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.utils.logger import setup_logger

logger = setup_logger()

# NOTE: all are made lowercase to avoid case sensitivity issues
# These field types are considered metadata by default when
# treat_all_non_attachment_fields_as_metadata is False
DEFAULT_METADATA_FIELD_TYPES = {
    "singlecollaborator",
    "collaborator",
    "createdby",
    "singleselect",
    "multipleselects",
    "checkbox",
    "date",
    "datetime",
    "email",
    "phone",
    "url",
    "number",
    "currency",
    "duration",
    "percent",
    "rating",
    "createdtime",
    "lastmodifiedtime",
    "autonumber",
    "rollup",
    "lookup",
    "count",
    "formula",
    "date",
}


class AirtableClientNotSetUpError(PermissionError):
    def __init__(self) -> None:
        super().__init__("Airtable Client is not set up, was load_credentials called?")


# Matches URLs like https://airtable.com/appXXX/tblYYY/viwZZZ?blocks=hide
# Captures: base_id (appXXX), table_id (tblYYY), and optionally view_id (viwZZZ)
_AIRTABLE_URL_PATTERN = re.compile(
    r"https?://airtable\.com/(app[A-Za-z0-9]+)/(tbl[A-Za-z0-9]+)(?:/(viw[A-Za-z0-9]+))?",
)


def parse_airtable_url(
    url: str,
) -> tuple[str, str, str | None]:
    """Parse an Airtable URL into (base_id, table_id, view_id).

    Accepts URLs like:
      https://airtable.com/appXXX/tblYYY
      https://airtable.com/appXXX/tblYYY/viwZZZ
      https://airtable.com/appXXX/tblYYY/viwZZZ?blocks=hide

    Returns:
        (base_id, table_id, view_id or None)

    Raises:
        ValueError if the URL doesn't match the expected format.
    """
    match = _AIRTABLE_URL_PATTERN.search(url.strip())
    if not match:
        raise ValueError(
            f"Could not parse Airtable URL: '{url}'. "
            "Expected format: https://airtable.com/appXXX/tblYYY[/viwZZZ]"
        )
    return match.group(1), match.group(2), match.group(3)


class AirtableConnector(LoadConnector):
    def __init__(
        self,
        base_id: str = "",
        table_name_or_id: str = "",
        airtable_url: str = "",
        treat_all_non_attachment_fields_as_metadata: bool = False,
        view_id: str | None = None,
        share_id: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        """Initialize an AirtableConnector.

        Args:
            base_id: The ID of the Airtable base (not required when airtable_url is set)
            table_name_or_id: The name or ID of the table (not required when airtable_url is set)
            airtable_url: An Airtable URL to parse base_id, table_id, and view_id from.
                Overrides base_id, table_name_or_id, and view_id if provided.
            treat_all_non_attachment_fields_as_metadata: If True, all fields except attachments will be treated as metadata.
                If False, only fields with types in DEFAULT_METADATA_FIELD_TYPES will be treated as metadata.
            view_id: Optional ID of a specific view to use
            share_id: Optional ID of a "share" to use for generating record URLs
            batch_size: Number of records to process in each batch

        Mode is auto-detected: if a specific table is identified (via URL or
        base_id + table_name_or_id), the connector indexes that single table.
        Otherwise, it discovers and indexes all accessible bases and tables.
        """
        # If a URL is provided, parse it to extract base_id, table_id, and view_id
        if airtable_url:
            parsed_base_id, parsed_table_id, parsed_view_id = parse_airtable_url(
                airtable_url
            )
            base_id = parsed_base_id
            table_name_or_id = parsed_table_id
            if parsed_view_id:
                view_id = parsed_view_id

        self.base_id = base_id
        self.table_name_or_id = table_name_or_id
        self.index_all = not (base_id and table_name_or_id)
        self.view_id = view_id
        self.share_id = share_id
        self.batch_size = batch_size
        self._airtable_client: AirtableApi | None = None
        self.treat_all_non_attachment_fields_as_metadata = (
            treat_all_non_attachment_fields_as_metadata
        )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._airtable_client = AirtableApi(credentials["airtable_access_token"])
        return None

    @property
    def airtable_client(self) -> AirtableApi:
        if not self._airtable_client:
            raise AirtableClientNotSetUpError()
        return self._airtable_client

    def validate_connector_settings(self) -> None:
        if self.index_all:
            try:
                bases = self.airtable_client.bases()
                if not bases:
                    raise ConnectorValidationError(
                        "No bases found. Ensure your API token has access to at least one base."
                    )
            except ConnectorValidationError:
                raise
            except Exception as e:
                raise ConnectorValidationError(f"Failed to list Airtable bases: {e}")
        else:
            if not self.base_id or not self.table_name_or_id:
                raise ConnectorValidationError(
                    "A valid Airtable URL or base_id and table_name_or_id are required "
                    "when not using index_all mode."
                )
            try:
                table = self.airtable_client.table(self.base_id, self.table_name_or_id)
                table.schema()
            except Exception as e:
                raise ConnectorValidationError(
                    f"Failed to access table '{self.table_name_or_id}' "
                    f"in base '{self.base_id}': {e}"
                )

    @classmethod
    def _get_record_url(
        cls,
        base_id: str,
        table_id: str,
        record_id: str,
        share_id: str | None,
        view_id: str | None,
        field_id: str | None = None,
        attachment_id: str | None = None,
    ) -> str:
        """Constructs the URL for a record, optionally including field and attachment IDs

        Full possible structure is:

        https://airtable.com/BASE_ID/SHARE_ID/TABLE_ID/VIEW_ID/RECORD_ID/FIELD_ID/ATTACHMENT_ID
        """
        # If we have a shared link, use that view for better UX
        if share_id:
            base_url = f"https://airtable.com/{base_id}/{share_id}/{table_id}"
        else:
            base_url = f"https://airtable.com/{base_id}/{table_id}"

        if view_id:
            base_url = f"{base_url}/{view_id}"

        base_url = f"{base_url}/{record_id}"

        if field_id and attachment_id:
            return f"{base_url}/{field_id}/{attachment_id}?blocks=hide"

        return base_url

    def _extract_field_values(
        self,
        field_id: str,
        field_name: str,
        field_info: Any,
        field_type: str,
        base_id: str,
        table_id: str,
        view_id: str | None,
        record_id: str,
    ) -> list[tuple[str, str]]:
        """
        Extract value(s) + links from a field regardless of its type.
        Attachments are represented as multiple sections, and therefore
        returned as a list of tuples (value, link).
        """
        if field_info is None:
            return []

        # skip references to other records for now (would need to do another
        # request to get the actual record name/type)
        # TODO: support this
        if field_type == "multipleRecordLinks":
            return []

        # Get the base URL for this record
        default_link = self._get_record_url(
            base_id, table_id, record_id, self.share_id, self.view_id or view_id
        )

        if field_type == "multipleAttachments":
            attachment_texts: list[tuple[str, str]] = []
            for attachment in field_info:
                url = attachment.get("url")
                filename = attachment.get("filename", "")
                if not url:
                    continue

                @retry(
                    tries=5,
                    delay=1,
                    backoff=2,
                    max_delay=10,
                )
                def get_attachment_with_retry(url: str, record_id: str) -> bytes | None:
                    try:
                        attachment_response = requests.get(url)
                        attachment_response.raise_for_status()
                        return attachment_response.content
                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code == 410:
                            logger.info(f"Refreshing attachment for {filename}")
                            # Re-fetch the record to get a fresh URL
                            refreshed_record = self.airtable_client.table(
                                base_id, table_id
                            ).get(record_id)
                            for refreshed_attachment in refreshed_record["fields"][
                                field_name
                            ]:
                                if refreshed_attachment.get("filename") == filename:
                                    new_url = refreshed_attachment.get("url")
                                    if new_url:
                                        attachment_response = requests.get(new_url)
                                        attachment_response.raise_for_status()
                                        return attachment_response.content

                            logger.error(f"Failed to refresh attachment for {filename}")
                        raise

                attachment_content = get_attachment_with_retry(url, record_id)
                if attachment_content:
                    try:
                        file_ext = get_file_ext(filename)
                        attachment_id = attachment["id"]
                        attachment_text = extract_file_text(
                            BytesIO(attachment_content),
                            filename,
                            break_on_unprocessable=False,
                            extension=file_ext,
                        )
                        if attachment_text:
                            # Use the helper method to construct attachment URLs
                            attachment_link = self._get_record_url(
                                base_id,
                                table_id,
                                record_id,
                                self.share_id,
                                self.view_id or view_id,
                                field_id,
                                attachment_id,
                            )
                            attachment_texts.append(
                                (f"{filename}:\n{attachment_text}", attachment_link)
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to process attachment {filename}: {str(e)}"
                        )
            return attachment_texts

        if field_type in ["singleCollaborator", "collaborator", "createdBy"]:
            combined = []
            collab_name = field_info.get("name")
            collab_email = field_info.get("email")
            if collab_name:
                combined.append(collab_name)
            if collab_email:
                combined.append(f"({collab_email})")
            return [(" ".join(combined) if combined else str(field_info), default_link)]

        if isinstance(field_info, list):
            return [(str(item), default_link) for item in field_info]

        return [(str(field_info), default_link)]

    def _should_be_metadata(self, field_type: str) -> bool:
        """Determine if a field type should be treated as metadata.

        When treat_all_non_attachment_fields_as_metadata is True, all fields except
        attachments are treated as metadata. Otherwise, only fields with types listed
        in DEFAULT_METADATA_FIELD_TYPES are treated as metadata."""
        if self.treat_all_non_attachment_fields_as_metadata:
            return field_type.lower() != "multipleattachments"
        return field_type.lower() in DEFAULT_METADATA_FIELD_TYPES

    def _process_field(
        self,
        field_id: str,
        field_name: str,
        field_info: Any,
        field_type: str,
        base_id: str,
        table_id: str,
        view_id: str | None,
        record_id: str,
    ) -> tuple[list[TextSection], dict[str, str | list[str]]]:
        """
        Process a single Airtable field and return sections or metadata.

        Args:
            field_name: Name of the field
            field_info: Raw field information from Airtable
            field_type: Airtable field type

        Returns:
            (list of Sections, dict of metadata)
        """
        if field_info is None:
            return [], {}

        # Get the value(s) for the field
        field_value_and_links = self._extract_field_values(
            field_id=field_id,
            field_name=field_name,
            field_info=field_info,
            field_type=field_type,
            base_id=base_id,
            table_id=table_id,
            view_id=view_id,
            record_id=record_id,
        )
        if len(field_value_and_links) == 0:
            return [], {}

        # Determine if it should be metadata or a section
        if self._should_be_metadata(field_type):
            field_values = [value for value, _ in field_value_and_links]
            if len(field_values) > 1:
                return [], {field_name: field_values}
            return [], {field_name: field_values[0]}

        # Otherwise, create relevant sections
        sections = [
            TextSection(
                link=link,
                text=(
                    f"{field_name}:\n"
                    "------------------------\n"
                    f"{text}\n"
                    "------------------------"
                ),
            )
            for text, link in field_value_and_links
        ]
        return sections, {}

    def _process_record(
        self,
        record: RecordDict,
        table_schema: TableSchema,
        primary_field_name: str | None,
        base_id: str,
        base_name: str | None = None,
    ) -> Document | None:
        """Process a single Airtable record into a Document.

        Args:
            record: The Airtable record to process
            table_schema: Schema information for the table
            primary_field_name: Name of the primary field, if any
            base_id: The ID of the base this record belongs to
            base_name: The name of the base (used in semantic ID for index_all mode)

        Returns:
            Document object representing the record
        """
        table_id = table_schema.id
        table_name = table_schema.name
        record_id = record["id"]
        fields = record["fields"]
        sections: list[TextSection] = []
        metadata: dict[str, str | list[str]] = {}

        # Get primary field value if it exists
        primary_field_value = (
            fields.get(primary_field_name) if primary_field_name else None
        )
        view_id = table_schema.views[0].id if table_schema.views else None

        for field_schema in table_schema.fields:
            field_name = field_schema.name
            field_val = fields.get(field_name)
            field_type = field_schema.type

            logger.debug(
                f"Processing field '{field_name}' of type '{field_type}' "
                f"for record '{record_id}'."
            )

            field_sections, field_metadata = self._process_field(
                field_id=field_schema.id,
                field_name=field_name,
                field_info=field_val,
                field_type=field_type,
                base_id=base_id,
                table_id=table_id,
                view_id=view_id,
                record_id=record_id,
            )

            sections.extend(field_sections)
            metadata.update(field_metadata)

        if not sections:
            logger.warning(f"No sections found for record {record_id}")
            return None

        # Include base name in semantic ID only in index_all mode
        if self.index_all and base_name:
            semantic_id = (
                f"{base_name} > {table_name}: {primary_field_value}"
                if primary_field_value
                else f"{base_name} > {table_name}"
            )
        else:
            semantic_id = (
                f"{table_name}: {primary_field_value}"
                if primary_field_value
                else table_name
            )

        # Build hierarchy source_path for Craft file system subdirectory structure.
        # This creates: airtable/{base_name}/{table_name}/record.json
        source_path: list[str] = []
        if base_name:
            source_path.append(base_name)
        source_path.append(table_name)

        return Document(
            id=f"airtable__{record_id}",
            sections=(cast(list[TextSection | ImageSection], sections)),
            source=DocumentSource.AIRTABLE,
            semantic_identifier=semantic_id,
            metadata=metadata,
            doc_metadata={
                "hierarchy": {
                    "source_path": source_path,
                    "base_id": base_id,
                    "table_id": table_id,
                    "table_name": table_name,
                    **({"base_name": base_name} if base_name else {}),
                }
            },
        )

    def _resolve_base_name(self, base_id: str) -> str | None:
        """Try to resolve a human-readable base name from the API."""
        try:
            for base_info in self.airtable_client.bases():
                if base_info.id == base_id:
                    return base_info.name
        except Exception:
            logger.debug(f"Could not resolve base name for {base_id}")
        return None

    def _index_table(
        self,
        base_id: str,
        table_name_or_id: str,
        base_name: str | None = None,
    ) -> GenerateDocumentsOutput:
        """Index all records from a single table. Yields batches of Documents."""
        # Resolve base name for hierarchy if not provided
        if base_name is None:
            base_name = self._resolve_base_name(base_id)

        table = self.airtable_client.table(base_id, table_name_or_id)
        records = table.all()

        table_schema = table.schema()
        primary_field_name = None

        # Find a primary field from the schema
        for field in table_schema.fields:
            if field.id == table_schema.primary_field_id:
                primary_field_name = field.name
                break

        logger.info(
            f"Processing {len(records)} records from table "
            f"'{table_schema.name}' in base '{base_name or base_id}'."
        )

        if not records:
            return

        # Process records in parallel batches using ThreadPoolExecutor
        PARALLEL_BATCH_SIZE = 8
        max_workers = min(PARALLEL_BATCH_SIZE, len(records))

        for i in range(0, len(records), PARALLEL_BATCH_SIZE):
            batch_records = records[i : i + PARALLEL_BATCH_SIZE]
            record_documents: list[Document | HierarchyNode] = []

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit batch tasks
                future_to_record: dict[Future[Document | None], RecordDict] = {}
                for record in batch_records:
                    # Capture the current context so that the thread gets the current tenant ID
                    current_context = contextvars.copy_context()
                    future_to_record[
                        executor.submit(
                            current_context.run,
                            self._process_record,
                            record=record,
                            table_schema=table_schema,
                            primary_field_name=primary_field_name,
                            base_id=base_id,
                            base_name=base_name,
                        )
                    ] = record

                # Wait for all tasks in this batch to complete
                for future in as_completed(future_to_record):
                    record = future_to_record[future]
                    try:
                        document = future.result()
                        if document:
                            record_documents.append(document)
                    except Exception as e:
                        logger.exception(f"Failed to process record {record['id']}")
                        raise e

            if record_documents:
                yield record_documents

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Fetch all records from one or all tables.

        NOTE: Airtable does not support filtering by time updated, so
        we have to fetch all records every time.
        """
        if not self.airtable_client:
            raise AirtableClientNotSetUpError()

        if self.index_all:
            yield from self._load_all()
        else:
            yield from self._index_table(
                base_id=self.base_id,
                table_name_or_id=self.table_name_or_id,
            )

    def _load_all(self) -> GenerateDocumentsOutput:
        """Discover all bases and tables, then index everything."""
        bases = self.airtable_client.bases()
        logger.info(f"Discovered {len(bases)} Airtable base(s).")

        for base_info in bases:
            base_id = base_info.id
            base_name = base_info.name
            logger.info(f"Listing tables for base '{base_name}' ({base_id}).")

            try:
                base = self.airtable_client.base(base_id)
                tables = base.tables()
            except Exception:
                logger.exception(
                    f"Failed to list tables for base '{base_name}' ({base_id}), skipping."
                )
                continue

            logger.info(f"Found {len(tables)} table(s) in base '{base_name}'.")

            for table in tables:
                try:
                    yield from self._index_table(
                        base_id=base_id,
                        table_name_or_id=table.id,
                        base_name=base_name,
                    )
                except Exception:
                    logger.exception(
                        f"Failed to index table '{table.name}' ({table.id}) "
                        f"in base '{base_name}' ({base_id}), skipping."
                    )
                    continue
