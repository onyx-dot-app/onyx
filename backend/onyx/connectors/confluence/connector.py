from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import quote

from onyx.configs.app_configs import CONFLUENCE_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import CONFLUENCE_TIMEZONE_OFFSET
from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.onyx_confluence import build_confluence_client
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.confluence.utils import attachment_to_content
from onyx.connectors.confluence.utils import build_confluence_document_id
from onyx.connectors.confluence.utils import datetime_from_string
from onyx.connectors.confluence.utils import extract_text_from_confluence_html
from onyx.connectors.confluence.utils import validate_attachment_filetype
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.connectors.models import SlimDocument
from onyx.utils.logger import setup_logger

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
    "ancestors.restrictions.read.restrictions.user",
    "ancestors.restrictions.read.restrictions.group",
]

_SLIM_DOC_BATCH_SIZE = 5000

_ATTACHMENT_EXTENSIONS_TO_FILTER_OUT = [
    "png",
    "jpg",
    "jpeg",
    "gif",
    "mp4",
    "mov",
    "mp3",
    "wav",
]
_FULL_EXTENSION_FILTER_STRING = "".join(
    [
        f" and title!~'*.{extension}'"
        for extension in _ATTACHMENT_EXTENSIONS_TO_FILTER_OUT
    ]
)


class ConfluenceConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        wiki_base: str,
        is_cloud: bool,
        space: str = "",
        page_id: str = "",
        index_recursively: bool = False,
        cql_query: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        continue_on_failure: bool = CONTINUE_ON_CONNECTOR_FAILURE,
        # if a page has one of the labels specified in this list, we will just
        # skip it. This is generally used to avoid indexing extra sensitive
        # pages.
        labels_to_skip: list[str] = CONFLUENCE_CONNECTOR_LABELS_TO_SKIP,
        timezone_offset: float = CONFLUENCE_TIMEZONE_OFFSET,
    ) -> None:
        self.batch_size = batch_size
        self.continue_on_failure = continue_on_failure
        self._confluence_client: OnyxConfluence | None = None
        self.is_cloud = is_cloud

        # Remove trailing slash from wiki_base if present
        self.wiki_base = wiki_base.rstrip("/")

        """
        If nothing is provided, we default to fetching all pages
        Only one or none of the following options should be specified so
            the order shouldn't matter
        However, we use elif to ensure that only of the following is enforced
        """
        base_cql_page_query = "type=page"
        if cql_query:
            base_cql_page_query = cql_query
        elif page_id:
            if index_recursively:
                base_cql_page_query += f" and (ancestor='{page_id}' or id='{page_id}')"
            else:
                base_cql_page_query += f" and id='{page_id}'"
        elif space:
            uri_safe_space = quote(space)
            base_cql_page_query += f" and space='{uri_safe_space}'"

        self.base_cql_page_query = base_cql_page_query

        self.cql_label_filter = ""
        if labels_to_skip:
            labels_to_skip = list(set(labels_to_skip))
            comma_separated_labels = ",".join(
                f"'{quote(label)}'" for label in labels_to_skip
            )
            self.cql_label_filter = f" and label not in ({comma_separated_labels})"

        self.timezone: timezone = timezone(offset=timedelta(hours=timezone_offset))

    @property
    def confluence_client(self) -> OnyxConfluence:
        if self._confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence")
        return self._confluence_client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # see https://github.com/atlassian-api/atlassian-python-api/blob/master/atlassian/rest_client.py
        # for a list of other hidden constructor args
        self._confluence_client = build_confluence_client(
            credentials=credentials,
            is_cloud=self.is_cloud,
            wiki_base=self.wiki_base,
        )
        return None

    def _construct_page_query(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> str:
        page_query = self.base_cql_page_query + self.cql_label_filter

        # Add time filters
        if start:
            formatted_start_time = datetime.fromtimestamp(
                start, tz=self.timezone
            ).strftime("%Y-%m-%d %H:%M")
            page_query += f" and lastmodified >= '{formatted_start_time}'"
        if end:
            formatted_end_time = datetime.fromtimestamp(end, tz=self.timezone).strftime(
                "%Y-%m-%d %H:%M"
            )
            page_query += f" and lastmodified <= '{formatted_end_time}'"

        return page_query

    def _construct_attachment_query(self, confluence_page_id: str) -> str:
        attachment_query = f"type=attachment and container='{confluence_page_id}'"
        attachment_query += self.cql_label_filter
        attachment_query += _FULL_EXTENSION_FILTER_STRING
        return attachment_query

    def _get_comment_string_for_page_id(self, page_id: str) -> str:
        comment_string = ""

        comment_cql = f"type=comment and container='{page_id}'"
        comment_cql += self.cql_label_filter

        expand = ",".join(_COMMENT_EXPANSION_FIELDS)
        for comment in self.confluence_client.paginated_cql_retrieval(
            cql=comment_cql,
            expand=expand,
        ):
            comment_string += "\nComment:\n"
            comment_string += extract_text_from_confluence_html(
                confluence_client=self.confluence_client,
                confluence_object=comment,
                fetched_titles=set(),
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
        # The url and the id are the same
        object_url = build_confluence_document_id(
            self.wiki_base, confluence_object["_links"]["webui"], self.is_cloud
        )

        object_text = None
        # Extract text from page
        if confluence_object["type"] == "page":
            object_text = extract_text_from_confluence_html(
                confluence_client=self.confluence_client,
                confluence_object=confluence_object,
                fetched_titles={confluence_object.get("title", "")},
            )
            # Add comments to text
            object_text += self._get_comment_string_for_page_id(confluence_object["id"])
        elif confluence_object["type"] == "attachment":
            object_text = attachment_to_content(
                confluence_client=self.confluence_client, attachment=confluence_object
            )

        if object_text is None:
            # This only happens for attachments that are not parseable
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

    def _fetch_document_batches(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        doc_batch: list[Document] = []
        confluence_page_ids: list[str] = []

        page_query = self._construct_page_query(start, end)
        logger.debug(f"page_query: {page_query}")
        # Fetch pages as Documents
        for page in self.confluence_client.paginated_cql_retrieval(
            cql=page_query,
            expand=",".join(_PAGE_EXPANSION_FIELDS),
            limit=self.batch_size,
        ):
            logger.debug(f"_fetch_document_batches: {page['id']}")
            confluence_page_ids.append(page["id"])
            doc = self._convert_object_to_document(page)
            if doc is not None:
                doc_batch.append(doc)
            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        # Fetch attachments as Documents
        for confluence_page_id in confluence_page_ids:
            attachment_query = self._construct_attachment_query(confluence_page_id)
            # TODO: maybe should add time filter as well?
            for attachment in self.confluence_client.paginated_cql_retrieval(
                cql=attachment_query,
                expand=",".join(_ATTACHMENT_EXPANSION_FIELDS),
            ):
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

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        return self._fetch_document_batches(start, end)

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateSlimDocumentOutput:
        doc_metadata_list: list[SlimDocument] = []

        restrictions_expand = ",".join(_RESTRICTIONS_EXPANSION_FIELDS)

        page_query = self.base_cql_page_query + self.cql_label_filter
        for page in self.confluence_client.cql_paginate_all_expansions(
            cql=page_query,
            expand=restrictions_expand,
            limit=_SLIM_DOC_BATCH_SIZE,
        ):
            # If the page has restrictions, add them to the perm_sync_data
            # These will be used by doc_sync.py to sync permissions
            page_restrictions = page.get("restrictions")
            page_space_key = page.get("space", {}).get("key")
            page_ancestors = page.get("ancestors", [])
            page_perm_sync_data = {
                "restrictions": page_restrictions or {},
                "space_key": page_space_key,
                "ancestors": page_ancestors or [],
            }

            doc_metadata_list.append(
                SlimDocument(
                    id=build_confluence_document_id(
                        self.wiki_base,
                        page["_links"]["webui"],
                        self.is_cloud,
                    ),
                    perm_sync_data=page_perm_sync_data,
                )
            )
            attachment_query = self._construct_attachment_query(page["id"])
            for attachment in self.confluence_client.cql_paginate_all_expansions(
                cql=attachment_query,
                expand=restrictions_expand,
                limit=_SLIM_DOC_BATCH_SIZE,
            ):
                if not validate_attachment_filetype(attachment):
                    continue
                attachment_restrictions = attachment.get("restrictions")
                if not attachment_restrictions:
                    attachment_restrictions = page_restrictions

                attachment_space_key = attachment.get("space", {}).get("key")
                if not attachment_space_key:
                    attachment_space_key = page_space_key

                attachment_perm_sync_data = {
                    "restrictions": attachment_restrictions or {},
                    "space_key": attachment_space_key,
                }

                doc_metadata_list.append(
                    SlimDocument(
                        id=build_confluence_document_id(
                            self.wiki_base,
                            attachment["_links"]["webui"],
                            self.is_cloud,
                        ),
                        perm_sync_data=attachment_perm_sync_data,
                    )
                )
            if len(doc_metadata_list) > _SLIM_DOC_BATCH_SIZE:
                yield doc_metadata_list[:_SLIM_DOC_BATCH_SIZE]
                doc_metadata_list = doc_metadata_list[_SLIM_DOC_BATCH_SIZE:]

        yield doc_metadata_list
