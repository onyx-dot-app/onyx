from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import quote

from requests.exceptions import HTTPError

from onyx.configs.app_configs import CONFLUENCE_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import CONFLUENCE_TIMEZONE_OFFSET
from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.app_configs import DISABLE_INDEXING_TIME_IMAGE_ANALYSIS
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.onyx_confluence import build_confluence_client
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.confluence.utils import build_confluence_document_id
from onyx.connectors.confluence.utils import convert_attachment_to_content
from onyx.connectors.confluence.utils import datetime_from_string
from onyx.connectors.confluence.utils import extract_text_from_confluence_html
from onyx.connectors.confluence.utils import validate_attachment_filetype
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedError
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
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.llm.factory import get_default_llm_with_vision
from onyx.utils.logger import setup_logger

logger = setup_logger()

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
        labels_to_skip: list[str] = CONFLUENCE_CONNECTOR_LABELS_TO_SKIP,
        timezone_offset: float = CONFLUENCE_TIMEZONE_OFFSET,
    ) -> None:
        self.batch_size = batch_size
        self.continue_on_failure = continue_on_failure
        self._confluence_client: OnyxConfluence | None = None
        self.is_cloud = is_cloud

        # Remove trailing slash from wiki_base if present
        self.wiki_base = wiki_base.rstrip("/")

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

        if not DISABLE_INDEXING_TIME_IMAGE_ANALYSIS:
            self.image_analysis_llm = get_default_llm_with_vision()
            if self.image_analysis_llm is None:
                logger.warning(
                    "No LLM with vision found; image summarization will be disabled"
                )

    @property
    def confluence_client(self) -> OnyxConfluence:
        if self._confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence")
        return self._confluence_client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
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

    def _convert_page_to_document(self, page: dict[str, Any]) -> Document | None:
        """
        Extract text from a Confluence page (plus its comments),
        create a Document containing a single Section for the page body.
        """
        if not page or "type" not in page or page["type"] != "page":
            return None

        # The url / ID for the page
        object_url = build_confluence_document_id(
            self.wiki_base, page["_links"]["webui"], self.is_cloud
        )

        # page text
        object_text = extract_text_from_confluence_html(
            confluence_client=self.confluence_client,
            confluence_object=page,
            fetched_titles={page.get("title", "")},
        )
        # Add comments
        object_text += self._get_comment_string_for_page_id(page["id"])

        # Get space name
        doc_metadata: dict[str, Any] = {}
        if page.get("space", {}).get("name"):
            doc_metadata["Wiki Space Name"] = page["space"]["name"]

        # labels
        label_dicts = page.get("metadata", {}).get("labels", {}).get("results", [])
        page_labels = [label.get("name") for label in label_dicts if label.get("name")]
        if page_labels:
            doc_metadata["labels"] = page_labels

        # last modified time + author
        version_dict = page.get("version", {})
        last_modified = (
            datetime_from_string(version_dict["when"])
            if "when" in version_dict
            else None
        )
        author_email = version_dict.get("by", {}).get("email")

        # Title
        page_title = page.get("title", "Untitled Document")

        return Document(
            id=object_url,
            sections=[Section(text=object_text, link=object_url, image_url=None)],
            source=DocumentSource.CONFLUENCE,
            semantic_identifier=page_title,
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
            confluence_xml = page.get("body", {}).get("storage", {}).get("value", "")

            for attachment in self.confluence_client.paginated_cql_retrieval(
                cql=attachment_query,
                expand=",".join(_ATTACHMENT_EXPANSION_FIELDS),
            ):
                media_type = attachment["metadata"].get("mediaType", "")
                if not validate_attachment_filetype(media_type):
                    continue

                # Attempt to get textual content or image summarization:
                try:
                    response = convert_attachment_to_content(
                        confluence_client=self.confluence_client,
                        attachment=attachment,
                        page_context=confluence_xml,
                        llm=self.image_analysis_llm,
                    )
                    if response is None:
                        continue

                    content_text, file_storage_name = response

                    object_url = build_confluence_document_id(
                        self.wiki_base, page["_links"]["webui"], self.is_cloud
                    )

                    if content_text:
                        doc.sections.append(
                            Section(
                                text=content_text,
                                link=object_url,
                                image_url=file_storage_name,
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
                "ancestors": page_ancestors or [],
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
                media_type = attachment["metadata"].get("mediaType", "")
                if not validate_attachment_filetype(media_type):
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
            raise UnexpectedError(
                f"Unexpected Confluence error (status={status_code}): {e}"
            )
        except Exception as e:
            raise UnexpectedError(
                f"Unexpected error while validating Confluence settings: {e}"
            )

        if not spaces or not spaces.get("results"):
            raise ConnectorValidationError(
                "No Confluence spaces found. Either your credentials lack permissions, or "
                "there truly are no spaces in this Confluence instance."
            )
