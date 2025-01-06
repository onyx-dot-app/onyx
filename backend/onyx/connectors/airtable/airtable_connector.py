from io import BytesIO
from typing import Any

import requests
from pyairtable import Api as AirtableApi
from pyairtable.api.types import RecordDict
from pyairtable.models.schema import TableSchema
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.utils.logger import setup_logger

logger = setup_logger()

# NOTE: all are made lowercase to avoid case sensitivity issues
# these are the field types that are considered metadata rather
# than sections
_METADATA_FIELD_TYPES = {
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


class AirtableConnector(LoadConnector):
    def __init__(
        self,
        base_id: str,
        table_name_or_id: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.base_id = base_id
        self.table_name_or_id = table_name_or_id
        self.batch_size = batch_size
        self.airtable_client: AirtableApi | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.airtable_client = AirtableApi(credentials["airtable_access_token"])
        return None

    def _get_field_value(self, field_info: Any, field_type: str) -> list[str]:
        """
        Extract value(s) from a field regardless of its type.
        Returns either a single string or list of strings for attachments.
        """
        if field_info is None:
            return []

        # skip references to other records for now (would need to do another
        # request to get the actual record name/type)
        # TODO: support this
        if field_type == "multipleRecordLinks":
            return []

        if field_type == "multipleAttachments":
            attachment_texts: list[str] = []
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
                def get_attachment_with_retry(url: str) -> bytes | None:
                    attachment_response = requests.get(url)
                    if attachment_response.status_code == 200:
                        return attachment_response.content
                    return None

                attachment_content = get_attachment_with_retry(url)
                if attachment_content:
                    try:
                        file_ext = get_file_ext(filename)
                        attachment_text = extract_file_text(
                            BytesIO(attachment_content),
                            filename,
                            break_on_unprocessable=False,
                            extension=file_ext,
                        )
                        if attachment_text:
                            attachment_texts.append(f"{filename}:\n{attachment_text}")
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
            return [" ".join(combined) if combined else str(field_info)]

        if isinstance(field_info, list):
            return [str(item) for item in field_info]

        return [str(field_info)]

    def _should_be_metadata(self, field_type: str) -> bool:
        """Determine if a field type should be treated as metadata."""
        return field_type.lower() in _METADATA_FIELD_TYPES

    def _process_field(
        self,
        field_name: str,
        field_info: Any,
        field_type: str,
        table_id: str,
        record_id: str,
    ) -> tuple[list[Section], dict[str, Any]]:
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
        field_values = self._get_field_value(field_info, field_type)
        if len(field_values) == 0:
            return [], {}

        # Determine if it should be metadata or a section
        if self._should_be_metadata(field_type):
            if len(field_values) > 1:
                return [], {field_name: field_values}
            return [], {field_name: field_values[0]}

        # Otherwise, create relevant sections
        sections = [
            Section(
                link=f"https://airtable.com/{self.base_id}/{table_id}/{record_id}",
                text=(
                    f"{field_name}:\n"
                    "------------------------\n"
                    f"{text}\n"
                    "------------------------"
                ),
            )
            for text in field_values
        ]
        return sections, {}

    def _process_record(
        self,
        record: RecordDict,
        table_schema: TableSchema,
        primary_field_name: str | None,
    ) -> Document:
        """Process a single Airtable record into a Document.

        Args:
            record: The Airtable record to process
            table_schema: Schema information for the table
            table_name: Name of the table
            table_id: ID of the table
            primary_field_name: Name of the primary field, if any

        Returns:
            Document object representing the record
        """
        table_id = table_schema.id
        table_name = table_schema.name
        record_id = record["id"]
        fields = record["fields"]
        sections: list[Section] = []
        metadata: dict[str, Any] = {}

        # Get primary field value if it exists
        primary_field_value = (
            fields.get(primary_field_name) if primary_field_name else None
        )

        for field_schema in table_schema.fields:
            field_name = field_schema.name
            field_val = fields.get(field_name)
            field_type = field_schema.type

            field_sections, field_metadata = self._process_field(
                field_name=field_name,
                field_info=field_val,
                field_type=field_type,
                table_id=table_id,
                record_id=record_id,
            )

            sections.extend(field_sections)
            metadata.update(field_metadata)

        semantic_id = (
            f"{table_name}: {primary_field_value}"
            if primary_field_value
            else table_name
        )

        return Document(
            id=f"airtable__{record_id}",
            sections=sections,
            source=DocumentSource.AIRTABLE,
            semantic_identifier=semantic_id,
            metadata=metadata,
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Fetch all records from the table.

        NOTE: Airtable does not support filtering by time updated, so
        we have to fetch all records every time.
        """
        if not self.airtable_client:
            raise AirtableClientNotSetUpError()

        table = self.airtable_client.table(self.base_id, self.table_name_or_id)
        records = table.all()

        table_schema = table.schema()
        primary_field_name = None

        # Find a primary field from the schema
        for field in table_schema.fields:
            if field.id == table_schema.primary_field_id:
                primary_field_name = field.name
                break

        record_documents: list[Document] = []
        for record in records:
            document = self._process_record(
                record=record,
                table_schema=table_schema,
                primary_field_name=primary_field_name,
            )
            record_documents.append(document)

            if len(record_documents) >= self.batch_size:
                yield record_documents
                record_documents = []

        if record_documents:
            yield record_documents
