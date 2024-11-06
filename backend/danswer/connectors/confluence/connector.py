from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import quote

from danswer.configs.app_configs import CONFLUENCE_CONNECTOR_LABELS_TO_SKIP
from danswer.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.confluence.onyx_confluence import OnyxConfluence
from danswer.connectors.confluence.utils import attachment_to_content
from danswer.connectors.confluence.utils import build_confluence_client
from danswer.connectors.confluence.utils import build_confluence_document_id
from danswer.connectors.confluence.utils import datetime_from_string
from danswer.connectors.confluence.utils import extract_text_from_confluence_html
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import GenerateSlimDocumentOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SlimConnector
from danswer.connectors.models import BasicExpertInfo
from danswer.connectors.models import ConnectorMissingCredentialError
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.connectors.models import SlimDocument
from danswer.utils.logger import setup_logger

logger = setup_logger()

# Potential Improvements
# 1. Include attachments, etc
# 2. Segment into Sections for more accurate linking, can split by headers but make sure no text/ordering is lost

_COMMENT_EXPANSION_FIELDS = ["body.storage.value"]
_PAGE_EXPANSION_FIELDS = [
    "body.storage.value",
    "version",
    "space",
    "metadata.labels",
]
_ATTACHMENT_EXPANSION_FIELDS = [
    "version",
    "space",
    "metadata.labels",
]

_RESTRICTIONS_EXPANSION_FIELDS = [
    "space",
    "restrictions.read.restrictions.user",
    "restrictions.read.restrictions.group",
]


class ConfluenceConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        wiki_base: str,
        is_cloud: bool,
        space: str = "",
        page_id: str = "",
        index_recursively: bool = True,
        cql_query: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        continue_on_failure: bool = CONTINUE_ON_CONNECTOR_FAILURE,
        # if a page has one of the labels specified in this list, we will just
        # skip it. This is generally used to avoid indexing extra sensitive
        # pages.
        labels_to_skip: list[str] = CONFLUENCE_CONNECTOR_LABELS_TO_SKIP,
    ) -> None:
        self.batch_size = batch_size
        self.continue_on_failure = continue_on_failure
        self.confluence_client: OnyxConfluence | None = None
        self.is_cloud = is_cloud

        # Remove trailing slash from wiki_base if present
        self.wiki_base = wiki_base.rstrip("/")

        # if nothing is provided, we will fetch all pages
        cql_page_query = "type=page"
        if cql_query:
            # if a cql_query is provided, we will use it to fetch the pages
            cql_page_query = cql_query
        elif space:
            # if no cql_query is provided, we will use the space to fetch the pages
            cql_page_query += f" and space='{quote(space)}'"
        elif page_id:
            if index_recursively:
                cql_page_query += f" and ancestor='{page_id}'"
            else:
                # if neither a space nor a cql_query is provided, we will use the page_id to fetch the page
                cql_page_query += f" and id='{page_id}'"

        self.cql_page_query = cql_page_query
        self.cql_time_filter = ""

        self.cql_label_filter = ""
        if labels_to_skip:
            labels_to_skip = list(set(labels_to_skip))
            comma_separated_labels = ",".join(f"'{label}'" for label in labels_to_skip)
            self.cql_label_filter = f" and label not in ({comma_separated_labels})"

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # see https://github.com/atlassian-api/atlassian-python-api/blob/master/atlassian/rest_client.py
        # for a list of other hidden constructor args
        self.confluence_client = build_confluence_client(
            credentials_json=credentials,
            is_cloud=self.is_cloud,
            wiki_base=self.wiki_base,
        )
        return None

    def _get_comment_string_for_page_id(self, page_id: str) -> str:
        if self.confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence")

        comment_string = ""

        comment_cql = f"type=comment and container='{page_id}'"
        comment_cql += self.cql_label_filter

        expand = ",".join(_COMMENT_EXPANSION_FIELDS)
        for comments in self.confluence_client.paginated_cql_page_retrieval(
            cql=comment_cql,
            expand=expand,
        ):
            for comment in comments:
                comment_string += "\nComment:\n"
                comment_string += extract_text_from_confluence_html(
                    confluence_client=self.confluence_client,
                    confluence_object=comment,
                )

        return comment_string

    def _convert_object_to_document(
        self, confluence_object: dict[str, Any]
    ) -> Document | None:
        """
        Takes in a confluence object, extracts all metadata, and converts it into a document.
        If its a page, it extracts the text, adds the comments for the document text.
        If its an attachment, it just downloads the attachment and converts that into a document.
        """
        if self.confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence")

        # The url and the id are the same
        object_url = build_confluence_document_id(
            self.wiki_base, confluence_object["_links"]["webui"]
        )

        object_text = None
        # Extract text from page
        if confluence_object["type"] == "page":
            object_text = extract_text_from_confluence_html(
                self.confluence_client, confluence_object
            )
            # Add comments to text
            object_text += self._get_comment_string_for_page_id(confluence_object["id"])
        elif confluence_object["type"] == "attachment":
            object_text = attachment_to_content(
                self.confluence_client, confluence_object
            )

        if object_text is None:
            return None

        # Get space name
        doc_metadata: dict[str, str | list[str]] = {
            "Wiki Space Name": confluence_object["space"]["name"]
        }

        # Get labels
        label_dicts = confluence_object["metadata"]["labels"]["results"]
        page_labels = [label["name"] for label in label_dicts]
        if page_labels:
            doc_metadata["labels"] = page_labels

        # Get last modified and author email
        last_modified = datetime_from_string(confluence_object["version"]["when"])
        author_email = confluence_object["version"].get("by", {}).get("email")

        return Document(
            id=object_url,
            sections=[Section(link=object_url, text=object_text)],
            source=DocumentSource.CONFLUENCE,
            semantic_identifier=confluence_object["title"],
            doc_updated_at=last_modified,
            primary_owners=(
                [BasicExpertInfo(email=author_email)] if author_email else None
            ),
            metadata=doc_metadata,
        )

    def _fetch_document_batches(self) -> GenerateDocumentsOutput:
        if self.confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence")

        doc_batch: list[Document] = []
        confluence_page_ids: list[str] = []

        page_query = self.cql_page_query + self.cql_label_filter + self.cql_time_filter
        # Fetch pages as Documents
        for page_batch in self.confluence_client.paginated_cql_page_retrieval(
            cql=page_query,
            expand=",".join(_PAGE_EXPANSION_FIELDS),
            limit=self.batch_size,
        ):
            for page in page_batch:
                confluence_page_ids.append(page["id"])
                doc = self._convert_object_to_document(page)
                if doc is not None:
                    doc_batch.append(doc)
                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

        # Fetch attachments as Documents
        for confluence_page_id in confluence_page_ids:
            attachment_cql = f"type=attachment and container='{confluence_page_id}'"
            attachment_cql += self.cql_label_filter
            # TODO: maybe should add time filter as well?
            for attachments in self.confluence_client.paginated_cql_page_retrieval(
                cql=attachment_cql,
                expand=",".join(_ATTACHMENT_EXPANSION_FIELDS),
            ):
                for attachment in attachments:
                    doc = self._convert_object_to_document(attachment)
                    if doc is not None:
                        doc_batch.append(doc)
                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_document_batches()

    def poll_source(self, start: float, end: float) -> GenerateDocumentsOutput:
        # Add time filters
        formatted_start_time = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        formatted_end_time = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        self.cql_time_filter = f" and lastmodified >= '{formatted_start_time}'"
        self.cql_time_filter += f" and lastmodified <= '{formatted_end_time}'"
        return self._fetch_document_batches()

    def retrieve_all_slim_documents(self) -> GenerateSlimDocumentOutput:
        if self.confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence")

        doc_metadata_list: list[SlimDocument] = []

        restrictions_expand = ",".join(_RESTRICTIONS_EXPANSION_FIELDS)

        page_query = self.cql_page_query + self.cql_label_filter
        for pages in self.confluence_client.cql_paginate_all_expansions(
            cql=page_query,
            expand=restrictions_expand,
        ):
            for page in pages:
                # If the page has restrictions, add them to the perm_sync_data
                # These will be used by doc_sync.py to sync permissions
                perm_sync_data = {
                    "restrictions": page.get("restrictions", {}),
                    "space_key": page.get("space", {}).get("key"),
                }

                doc_metadata_list.append(
                    SlimDocument(
                        id=build_confluence_document_id(
                            self.wiki_base, page["_links"]["webui"]
                        ),
                        perm_sync_data=perm_sync_data,
                    )
                )
                attachment_cql = f"type=attachment and container='{page['id']}'"
                attachment_cql += self.cql_label_filter
                for attachments in self.confluence_client.cql_paginate_all_expansions(
                    cql=attachment_cql,
                    expand=restrictions_expand,
                ):
                    for attachment in attachments:
                        doc_metadata_list.append(
                            SlimDocument(
                                id=build_confluence_document_id(
                                    self.wiki_base, attachment["_links"]["webui"]
                                ),
                                perm_sync_data=perm_sync_data,
                            )
                        )
                yield doc_metadata_list
                doc_metadata_list = []
