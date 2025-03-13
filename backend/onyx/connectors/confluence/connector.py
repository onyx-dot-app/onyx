from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import quote

from requests.exceptions import HTTPError

from onyx.configs.app_configs import CONFLUENCE_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import CONFLUENCE_TIMEZONE_OFFSET
from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.onyx_confluence import extract_text_from_confluence_html
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.confluence.utils import build_confluence_document_id
from onyx.connectors.confluence.utils import convert_attachment_to_content
from onyx.connectors.confluence.utils import datetime_from_string
from onyx.connectors.confluence.utils import process_attachment
from onyx.connectors.confluence.utils import validate_attachment_filetype
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CredentialsConnector
from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()
# Potential Improvements
# 1. Segment into Sections for more accurate linking, can split by headers but make sure no text/ordering is lost
_COMMENT_EXPANSION_FIELDS = ["body.storage.value"]
_PAGE_EXPANSION_FIELDS = [
    "body.storage.value",
    "version",
    "space",
    "metadata.labels",
    "history.lastUpdated",
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


class ConfluenceConnector(
    LoadConnector,
    PollConnector,
    SlimConnector,
    CredentialsConnector,
):
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
        self.wiki_base = wiki_base
        self.is_cloud = is_cloud
        self.space = space
        self.page_id = page_id
        self.index_recursively = index_recursively
        self.cql_query = cql_query
        self.batch_size = batch_size
        self.continue_on_failure = continue_on_failure
        self.labels_to_skip = labels_to_skip
        self.timezone_offset = timezone_offset
        self._confluence_client: OnyxConfluence | None = None
        self._fetched_titles: set[str] = set()

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
        self.credentials_provider: CredentialsProviderInterface | None = None

        self.probe_kwargs = {
            "max_backoff_retries": 6,
            "max_backoff_seconds": 10,
        }

        self.final_kwargs = {
            "max_backoff_retries": 10,
            "max_backoff_seconds": 60,
        }

    @property
    def confluence_client(self) -> OnyxConfluence:
        if self._confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence")
        return self._confluence_client

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self.credentials_provider = credentials_provider

        # raises exception if there's a problem
        confluence_client = OnyxConfluence(
            self.is_cloud, self.wiki_base, credentials_provider
        )
        confluence_client._probe_connection(**self.probe_kwargs)
        confluence_client._initialize_connection(**self.final_kwargs)

        self._confluence_client = confluence_client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use set_credentials_provider with this connector.")

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

    def _convert_page_to_document(self, page: dict[str, Any]) -> Document | None:
        """
        Converts a Confluence page to a Document object.
        Includes the page content, comments, and attachments.
        """
        try:
            # Extract basic page information
            page_id = page["id"]
            page_title = page["title"]
            page_url = f"{self.wiki_base}{page['_links']['webui']}"

            # Get the page content
            page_content = extract_text_from_confluence_html(
                self.confluence_client, page, self._fetched_titles
            )

            # Create the main section for the page content
            sections: list[TextSection | ImageSection] = [
                TextSection(text=page_content, link=page_url)
            ]

            # Process comments if available
            comment_text = self._get_comment_string_for_page_id(page_id)
            if comment_text:
                sections.append(
                    TextSection(text=comment_text, link=f"{page_url}#comments")
                )

            # Process attachments
            if "children" in page and "attachment" in page["children"]:
                attachments = self.confluence_client.get_attachments_for_page(
                    page_id, expand="metadata"
                )

                for attachment in attachments.get("results", []):
                    # Process each attachment
                    result = process_attachment(
                        self.confluence_client,
                        attachment,
                        page_id,
                    )

                    if result and result.text:
                        # Create a section for the attachment text
                        attachment_section = TextSection(
                            text=result.text,
                            link=f"{page_url}#attachment-{attachment['id']}",
                        )
                        sections.append(attachment_section)
                    elif result and result.file_name:
                        # Create an ImageSection for image attachments
                        image_section = ImageSection(
                            link=f"{page_url}#attachment-{attachment['id']}",
                            image_file_name=result.file_name,
                        )
                        sections.append(image_section)
                    else:
                        logger.warning(
                            f"Error processing attachment '{attachment.get('title')}':",
                            f"{result.error if result else 'Unknown error'}",
                        )

            # Extract metadata
            metadata = {}
            if "space" in page:
                metadata["space"] = page["space"].get("name", "")

            # Extract labels
            labels = []
            if "metadata" in page and "labels" in page["metadata"]:
                for label in page["metadata"]["labels"].get("results", []):
                    labels.append(label.get("name", ""))
            if labels:
                metadata["labels"] = labels

            # Extract owners
            primary_owners = []
            if "version" in page and "by" in page["version"]:
                author = page["version"]["by"]
                display_name = author.get("displayName", "Unknown")
                primary_owners.append(BasicExpertInfo(display_name=display_name))

            # Create the document
            return Document(
                id=build_confluence_document_id(
                    self.wiki_base, page["_links"]["webui"], self.is_cloud
                ),
                sections=sections,
                source=DocumentSource.CONFLUENCE,
                semantic_identifier=page_title,
                metadata=metadata,
                doc_updated_at=datetime_from_string(page["version"]["when"]),
                primary_owners=primary_owners if primary_owners else None,
            )
        except Exception as e:
            logger.error(f"Error converting page {page.get('id', 'unknown')}: {e}")
            if not self.continue_on_failure:
                raise
            return None

    def _fetch_document_batches(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        """
        Yields batches of Documents. For each page:
         - Create a Document with 1 Section for the page text/comments
         - Then fetch attachments. For each attachment:
             - Attempt to convert it with convert_attachment_to_content(...)
             - If successful, create a new Section with the extracted text or summary.
        """
        doc_batch: list[Document] = []

        page_query = self._construct_page_query(start, end)
        logger.debug(f"page_query: {page_query}")

        for page in self.confluence_client.paginated_cql_retrieval(
            cql=page_query,
            expand=",".join(_PAGE_EXPANSION_FIELDS),
            limit=self.batch_size,
        ):
            # Build doc from page
            doc = self._convert_page_to_document(page)
            if not doc:
                continue

            # Now get attachments for that page:
            attachment_query = self._construct_attachment_query(page["id"])
            # We'll use the page's XML to provide context if we summarize an image
            page.get("body", {}).get("storage", {}).get("value", "")

            for attachment in self.confluence_client.paginated_cql_retrieval(
                cql=attachment_query,
                expand=",".join(_ATTACHMENT_EXPANSION_FIELDS),
            ):
                attachment["metadata"].get("mediaType", "")
                if not validate_attachment_filetype(
                    attachment,
                ):
                    continue

                # Attempt to get textual content or image summarization:
                try:
                    logger.info(f"Processing attachment: {attachment['title']}")
                    response = convert_attachment_to_content(
                        confluence_client=self.confluence_client,
                        attachment=attachment,
                        page_id=page["id"],
                    )
                    if response is None:
                        continue

                    content_text, file_storage_name = response
                    object_url = build_confluence_document_id(
                        self.wiki_base, attachment["_links"]["webui"], self.is_cloud
                    )
                    if content_text:
                        doc.sections.append(
                            TextSection(
                                text=content_text,
                                link=object_url,
                            )
                        )
                    elif file_storage_name:
                        doc.sections.append(
                            ImageSection(
                                link=object_url,
                                image_file_name=file_storage_name,
                            )
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to extract/summarize attachment {attachment['title']}",
                        exc_info=e,
                    )
                    if not self.continue_on_failure:
                        raise

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
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """
        Return 'slim' docs (IDs + minimal permission data).
        Does not fetch actual text. Used primarily for incremental permission sync.
        """
        doc_metadata_list: list[SlimDocument] = []
        restrictions_expand = ",".join(_RESTRICTIONS_EXPANSION_FIELDS)

        # Query pages
        page_query = self.base_cql_page_query + self.cql_label_filter
        for page in self.confluence_client.cql_paginate_all_expansions(
            cql=page_query,
            expand=restrictions_expand,
            limit=_SLIM_DOC_BATCH_SIZE,
        ):
            page_restrictions = page.get("restrictions")
            page_space_key = page.get("space", {}).get("key")
            page_ancestors = page.get("ancestors", [])

            page_perm_sync_data = {
                "restrictions": page_restrictions or {},
                "space_key": page_space_key,
                "ancestors": page_ancestors,
            }

            doc_metadata_list.append(
                SlimDocument(
                    id=build_confluence_document_id(
                        self.wiki_base, page["_links"]["webui"], self.is_cloud
                    ),
                    perm_sync_data=page_perm_sync_data,
                )
            )

            # Query attachments for each page
            attachment_query = self._construct_attachment_query(page["id"])
            for attachment in self.confluence_client.cql_paginate_all_expansions(
                cql=attachment_query,
                expand=restrictions_expand,
                limit=_SLIM_DOC_BATCH_SIZE,
            ):
                # If you skip images, you'll skip them in the permission sync
                attachment["metadata"].get("mediaType", "")
                if not validate_attachment_filetype(
                    attachment,
                ):
                    continue

                attachment_restrictions = attachment.get("restrictions", {})
                if not attachment_restrictions:
                    attachment_restrictions = page_restrictions or {}

                attachment_space_key = attachment.get("space", {}).get("key")
                if not attachment_space_key:
                    attachment_space_key = page_space_key

                attachment_perm_sync_data = {
                    "restrictions": attachment_restrictions,
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

                if callback and callback.should_stop():
                    raise RuntimeError(
                        "retrieve_all_slim_documents: Stop signal detected"
                    )
                if callback:
                    callback.progress("retrieve_all_slim_documents", 1)

        yield doc_metadata_list

    def validate_connector_settings(self) -> None:
        if self._confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence credentials not loaded.")

        try:
            spaces = self._confluence_client.get_all_spaces(limit=1)
        except HTTPError as e:
            status_code = e.response.status_code if e.response else None
            if status_code == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Confluence credentials (HTTP 401)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Insufficient permissions to access Confluence resources (HTTP 403)."
                )
            raise UnexpectedValidationError(
                f"Unexpected Confluence error (status={status_code}): {e}"
            )
        except Exception as e:
            raise UnexpectedValidationError(
                f"Unexpected error while validating Confluence settings: {e}"
            )

        if not spaces or not spaces.get("results"):
            raise ConnectorValidationError(
                "No Confluence spaces found. Either your credentials lack permissions, or "
                "there truly are no spaces in this Confluence instance."
            )
