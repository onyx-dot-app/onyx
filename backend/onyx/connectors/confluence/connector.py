import copy
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import quote

from atlassian.errors import ApiError  # type: ignore
from requests.exceptions import HTTPError
from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import CONFLUENCE_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import CONFLUENCE_TIMEZONE_OFFSET
from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.access import get_all_space_permissions
from onyx.connectors.confluence.access import get_page_restrictions
from onyx.connectors.confluence.onyx_confluence import extract_text_from_confluence_html
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.confluence.utils import build_confluence_document_id
from onyx.connectors.confluence.utils import convert_attachment_to_content
from onyx.connectors.confluence.utils import datetime_from_string
from onyx.connectors.confluence.utils import update_param_in_path
from onyx.connectors.confluence.utils import validate_attachment_filetype
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    is_atlassian_date_error,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import ConnectorCheckpoint
from onyx.connectors.interfaces import ConnectorFailure
from onyx.connectors.interfaces import CredentialsConnector
from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
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

ONE_HOUR = 3600
ONE_DAY = ONE_HOUR * 24

MAX_CACHED_IDS = 100


class ConfluenceCheckpoint(ConnectorCheckpoint):

    next_page_url: str | None


class ConfluenceConnector(
    CheckpointedConnector[ConfluenceCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
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
        scoped_token: bool = False,
    ) -> None:
        self.wiki_base = wiki_base
        self.is_cloud = is_cloud
        self.space = space
        self.page_id = page_id
        self.index_recursively = index_recursively
        self.cql_query = cql_query
        self.batch_size = batch_size
        self.labels_to_skip = labels_to_skip
        self.timezone_offset = timezone_offset
        self.scoped_token = scoped_token
        self._confluence_client: OnyxConfluence | None = None
        self._low_timeout_confluence_client: OnyxConfluence | None = None
        self._fetched_titles: set[str] = set()
        self.allow_images = False

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

        # deprecated
        self.continue_on_failure = continue_on_failure

    def set_allow_images(self, value: bool) -> None:
        logger.info(f"Setting allow_images to {value}.")
        self.allow_images = value

    @property
    def confluence_client(self) -> OnyxConfluence:
        if self._confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence")
        return self._confluence_client

    @property
    def low_timeout_confluence_client(self) -> OnyxConfluence:
        if self._low_timeout_confluence_client is None:
            raise ConnectorMissingCredentialError("Confluence")
        return self._low_timeout_confluence_client

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self.credentials_provider = credentials_provider

        # raises exception if there's a problem
        confluence_client = OnyxConfluence(
            is_cloud=self.is_cloud,
            url=self.wiki_base,
            credentials_provider=credentials_provider,
            scoped_token=self.scoped_token,
        )
        confluence_client._probe_connection(**self.probe_kwargs)
        confluence_client._initialize_connection(**self.final_kwargs)

        self._confluence_client = confluence_client

        # create a low timeout confluence client for sync flows
        low_timeout_confluence_client = OnyxConfluence(
            is_cloud=self.is_cloud,
            url=self.wiki_base,
            credentials_provider=credentials_provider,
            timeout=3,
            scoped_token=self.scoped_token,
        )
        low_timeout_confluence_client._probe_connection(**self.probe_kwargs)
        low_timeout_confluence_client._initialize_connection(**self.final_kwargs)

        self._low_timeout_confluence_client = low_timeout_confluence_client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use set_credentials_provider with this connector.")

    def _construct_page_cql_query(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> str:
        """
        Constructs a CQL query for use in the confluence API. See
        https://developer.atlassian.com/server/confluence/advanced-searching-using-cql/
        for more information. This is JUST the CQL, not the full URL used to hit the API.
        Use _build_page_retrieval_url to get the full URL.
        """
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

        page_query += " order by lastmodified asc"
        return page_query

    def _construct_attachment_query(
        self,
        confluence_page_id: str,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> str:
        attachment_query = f"type=attachment and container='{confluence_page_id}'"
        attachment_query += self.cql_label_filter
        # Add time filters to avoid reprocessing unchanged attachments during refresh
        if start:
            formatted_start_time = datetime.fromtimestamp(
                start, tz=self.timezone
            ).strftime("%Y-%m-%d %H:%M")
            attachment_query += f" and lastmodified >= '{formatted_start_time}'"
        if end:
            formatted_end_time = datetime.fromtimestamp(end, tz=self.timezone).strftime(
                "%Y-%m-%d %H:%M"
            )
            attachment_query += f" and lastmodified <= '{formatted_end_time}'"
        attachment_query += " order by lastmodified asc"
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

    def _convert_page_to_document(
        self, page: dict[str, Any]
    ) -> Document | ConnectorFailure:
        """
        Converts a Confluence page to a Document object.
        Includes the page content, comments, and attachments.
        """
        page_id = page_url = ""
        try:
            # Extract basic page information
            page_id = page["id"]
            page_title = page["title"]
            logger.info(f"Converting page {page_title} to document")
            page_url = build_confluence_document_id(
                self.wiki_base, page["_links"]["webui"], self.is_cloud
            )

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
            # Note: attachments are no longer merged into the page document.
            # They are indexed as separate documents downstream.

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
                email = author.get("email", "unknown@domain.invalid")
                primary_owners.append(
                    BasicExpertInfo(display_name=display_name, email=email)
                )

            # Create the document
            return Document(
                id=page_url,
                sections=sections,
                source=DocumentSource.CONFLUENCE,
                semantic_identifier=page_title,
                metadata=metadata,
                doc_updated_at=datetime_from_string(page["version"]["when"]),
                primary_owners=primary_owners if primary_owners else None,
            )
        except Exception as e:
            logger.error(f"Error converting page {page.get('id', 'unknown')}: {e}")
            if is_atlassian_date_error(e):  # propagate error to be caught and retried
                raise
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=page_id,
                    document_link=page_url,
                ),
                failure_message=f"Error converting page {page.get('id', 'unknown')}: {e}",
                exception=e,
            )

    def _fetch_page_attachments(
        self,
        page: dict[str, Any],
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> tuple[list[Document], list[ConnectorFailure]]:
        """
        Inline attachments are added directly to the document as text or image sections by
        this function. The returned documents/connectorfailures are for non-inline attachments
        and those at the end of the page.
        """
        attachment_query = self._construct_attachment_query(page["id"], start, end)
        attachment_failures: list[ConnectorFailure] = []
        attachment_docs: list[Document] = []
        page_url = ""

        for attachment in self.confluence_client.paginated_cql_retrieval(
            cql=attachment_query,
            expand=",".join(_ATTACHMENT_EXPANSION_FIELDS),
        ):
            media_type: str = attachment.get("metadata", {}).get("mediaType", "")

            # TODO(rkuo): this check is partially redundant with validate_attachment_filetype
            # and checks in convert_attachment_to_content/process_attachment
            # but doing the check here avoids an unnecessary download. Due for refactoring.
            if not self.allow_images:
                if media_type.startswith("image/"):
                    logger.info(
                        f"Skipping attachment because allow images is False: {attachment['title']}"
                    )
                    continue

            if not validate_attachment_filetype(
                attachment,
            ):
                logger.info(
                    f"Skipping attachment because it is not an accepted file type: {attachment['title']}"
                )
                continue

            logger.info(
                f"Processing attachment: {attachment['title']} attached to page {page['title']}"
            )
            # Attachment document id: use the download URL for stable identity
            try:
                object_url = build_confluence_document_id(
                    self.wiki_base, attachment["_links"]["download"], self.is_cloud
                )
            except Exception as e:
                logger.warning(
                    f"Invalid attachment url for id {attachment['id']}, skipping"
                )
                logger.debug(f"Error building attachment url: {e}")
                continue
            try:
                response = convert_attachment_to_content(
                    confluence_client=self.confluence_client,
                    attachment=attachment,
                    page_id=page["id"],
                    allow_images=self.allow_images,
                )
                if response is None:
                    continue

                content_text, file_storage_name = response

                sections: list[TextSection | ImageSection] = []
                if content_text:
                    sections.append(TextSection(text=content_text, link=object_url))
                elif file_storage_name:
                    sections.append(
                        ImageSection(link=object_url, image_file_id=file_storage_name)
                    )

                # Build attachment-specific metadata
                attachment_metadata: dict[str, str | list[str]] = {}
                if "space" in attachment:
                    attachment_metadata["space"] = attachment["space"].get("name", "")
                labels: list[str] = []
                if "metadata" in attachment and "labels" in attachment["metadata"]:
                    for label in attachment["metadata"]["labels"].get("results", []):
                        labels.append(label.get("name", ""))
                if labels:
                    attachment_metadata["labels"] = labels
                page_url = page_url or build_confluence_document_id(
                    self.wiki_base, page["_links"]["webui"], self.is_cloud
                )
                attachment_metadata["parent_page_id"] = page_url
                attachment_id = build_confluence_document_id(
                    self.wiki_base, attachment["_links"]["webui"], self.is_cloud
                )

                primary_owners: list[BasicExpertInfo] | None = None
                if "version" in attachment and "by" in attachment["version"]:
                    author = attachment["version"]["by"]
                    display_name = author.get("displayName", "Unknown")
                    email = author.get("email", "unknown@domain.invalid")
                    primary_owners = [
                        BasicExpertInfo(display_name=display_name, email=email)
                    ]

                attachment_doc = Document(
                    id=attachment_id,
                    sections=sections,
                    source=DocumentSource.CONFLUENCE,
                    semantic_identifier=attachment.get("title", object_url),
                    metadata=attachment_metadata,
                    doc_updated_at=(
                        datetime_from_string(attachment["version"]["when"])
                        if attachment.get("version")
                        and attachment["version"].get("when")
                        else None
                    ),
                    primary_owners=primary_owners,
                )
                attachment_docs.append(attachment_doc)
            except Exception as e:
                logger.error(
                    f"Failed to extract/summarize attachment {attachment['title']}",
                    exc_info=e,
                )
                if is_atlassian_date_error(e):
                    # propagate error to be caught and retried
                    raise
                attachment_failures.append(
                    ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=object_url,
                            document_link=object_url,
                        ),
                        failure_message=f"Failed to extract/summarize attachment {attachment['title']} for doc {object_url}",
                        exception=e,
                    )
                )

        return attachment_docs, attachment_failures

    def _fetch_document_batches(
        self,
        checkpoint: ConfluenceCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> CheckpointOutput[ConfluenceCheckpoint]:
        """
        Yields batches of Documents. For each page:
         - Create a Document with 1 Section for the page text/comments
         - Then fetch attachments. For each attachment:
             - Attempt to convert it with convert_attachment_to_content(...)
             - If successful, create a new Section with the extracted text or summary.
        """
        checkpoint = copy.deepcopy(checkpoint)

        # use "start" when last_updated is 0 or for confluence server
        start_ts = start
        page_query_url = checkpoint.next_page_url or self._build_page_retrieval_url(
            start_ts, end, self.batch_size
        )
        logger.debug(f"page_query_url: {page_query_url}")

        # store the next page start for confluence server, cursor for confluence cloud
        def store_next_page_url(next_page_url: str) -> None:
            checkpoint.next_page_url = next_page_url

        for page in self.confluence_client.paginated_page_retrieval(
            cql_url=page_query_url,
            limit=self.batch_size,
            next_page_callback=store_next_page_url,
        ):
            # Build doc from page
            doc_or_failure = self._convert_page_to_document(page)

            if isinstance(doc_or_failure, ConnectorFailure):
                yield doc_or_failure
                continue

            # yield completed document (or failure)
            yield doc_or_failure

            # Now get attachments for that page:
            attachment_docs, attachment_failures = self._fetch_page_attachments(
                page, start, end
            )
            # yield attached docs and failures
            yield from attachment_docs
            yield from attachment_failures

            # Create checkpoint once a full page of results is returned
            if checkpoint.next_page_url and checkpoint.next_page_url != page_query_url:
                return checkpoint

        checkpoint.has_more = False
        return checkpoint

    def _build_page_retrieval_url(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        limit: int,
    ) -> str:
        """
        Builds the full URL used to retrieve pages from the confluence API.
        This can be used as input to the confluence client's _paginate_url
        or paginated_page_retrieval methods.
        """
        page_query = self._construct_page_cql_query(start, end)
        cql_url = self.confluence_client.build_cql_url(
            page_query, expand=",".join(_PAGE_EXPANSION_FIELDS)
        )
        return update_param_in_path(cql_url, "limit", str(limit))

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConfluenceCheckpoint,
    ) -> CheckpointOutput[ConfluenceCheckpoint]:
        end += ONE_DAY  # handle time zone weirdness
        try:
            return self._fetch_document_batches(checkpoint, start, end)
        except Exception as e:
            if is_atlassian_date_error(e) and start is not None:
                logger.warning(
                    "Confluence says we provided an invalid 'updated' field. This may indicate"
                    "a real issue, but can also appear during edge cases like daylight"
                    f"savings time changes. Retrying with a 1 hour offset. Error: {e}"
                )
                return self._fetch_document_batches(checkpoint, start - ONE_HOUR, end)
            raise

    @override
    def build_dummy_checkpoint(self) -> ConfluenceCheckpoint:
        return ConfluenceCheckpoint(has_more=True, next_page_url=None)

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> ConfluenceCheckpoint:
        return ConfluenceCheckpoint.model_validate_json(checkpoint_json)

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        return self._retrieve_all_slim_docs(
            start=start,
            end=end,
            callback=callback,
            include_permissions=False,
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """
        Return 'slim' docs (IDs + minimal permission data).
        Does not fetch actual text. Used primarily for incremental permission sync.
        """
        return self._retrieve_all_slim_docs(
            start=start,
            end=end,
            callback=callback,
            include_permissions=True,
        )

    def _retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
        include_permissions: bool = True,
    ) -> GenerateSlimDocumentOutput:
        doc_metadata_list: list[SlimDocument] = []
        restrictions_expand = ",".join(_RESTRICTIONS_EXPANSION_FIELDS)

        space_level_access_info: dict[str, ExternalAccess] = {}
        if include_permissions:
            space_level_access_info = get_all_space_permissions(
                self.confluence_client, self.is_cloud
            )

        def get_external_access(
            doc_id: str, restrictions: dict[str, Any], ancestors: list[dict[str, Any]]
        ) -> ExternalAccess | None:
            return get_page_restrictions(
                self.confluence_client, doc_id, restrictions, ancestors
            ) or space_level_access_info.get(page_space_key)

        # Query pages
        page_query = self.base_cql_page_query + self.cql_label_filter
        for page in self.confluence_client.cql_paginate_all_expansions(
            cql=page_query,
            expand=restrictions_expand,
            limit=_SLIM_DOC_BATCH_SIZE,
        ):
            page_id = page["id"]
            page_restrictions = page.get("restrictions") or {}
            page_space_key = page.get("space", {}).get("key")
            page_ancestors = page.get("ancestors", [])

            page_id = build_confluence_document_id(
                self.wiki_base, page["_links"]["webui"], self.is_cloud
            )
            doc_metadata_list.append(
                SlimDocument(
                    id=page_id,
                    external_access=(
                        get_external_access(page_id, page_restrictions, page_ancestors)
                        if include_permissions
                        else None
                    ),
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

                attachment_id = build_confluence_document_id(
                    self.wiki_base,
                    attachment["_links"]["webui"],
                    self.is_cloud,
                )
                doc_metadata_list.append(
                    SlimDocument(
                        id=attachment_id,
                        external_access=(
                            get_external_access(
                                attachment_id, attachment_restrictions, []
                            )
                            if include_permissions
                            else None
                        ),
                    )
                )

            if len(doc_metadata_list) > _SLIM_DOC_BATCH_SIZE:
                yield doc_metadata_list[:_SLIM_DOC_BATCH_SIZE]
                doc_metadata_list = doc_metadata_list[_SLIM_DOC_BATCH_SIZE:]

                if callback and callback.should_stop():
                    raise RuntimeError(
                        "retrieve_all_slim_docs_perm_sync: Stop signal detected"
                    )
                if callback:
                    callback.progress("retrieve_all_slim_docs_perm_sync", 1)

        yield doc_metadata_list

    def validate_connector_settings(self) -> None:
        try:
            spaces = self.low_timeout_confluence_client.get_all_spaces(limit=1)
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

        if self.space:
            try:
                self.low_timeout_confluence_client.get_space(self.space)
            except ApiError as e:
                raise ConnectorValidationError(
                    "Invalid Confluence space key provided"
                ) from e

        if not spaces or not spaces.get("results"):
            raise ConnectorValidationError(
                "No Confluence spaces found. Either your credentials lack permissions, or "
                "there truly are no spaces in this Confluence instance."
            )


if __name__ == "__main__":
    import os
    from onyx.utils.variable_functionality import global_version
    from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector

    # For connector permission testing, set EE to true.
    global_version.set_ee()

    # base url
    wiki_base = os.environ["CONFLUENCE_URL"]

    # auth stuff
    username = os.environ["CONFLUENCE_USERNAME"]
    access_token = os.environ["CONFLUENCE_ACCESS_TOKEN"]
    is_cloud = os.environ["CONFLUENCE_IS_CLOUD"].lower() == "true"

    # space + page
    space = os.environ["CONFLUENCE_SPACE_KEY"]
    # page_id = os.environ["CONFLUENCE_PAGE_ID"]

    confluence_connector = ConfluenceConnector(
        wiki_base=wiki_base,
        space=space,
        is_cloud=is_cloud,
        # page_id=page_id,
    )

    credentials_provider = OnyxStaticCredentialsProvider(
        None,
        DocumentSource.CONFLUENCE,
        {
            "confluence_username": username,
            "confluence_access_token": access_token,
        },
    )
    confluence_connector.set_credentials_provider(credentials_provider)

    start = 0.0
    end = datetime.now().timestamp()

    # Fetch all `SlimDocuments`.
    for slim_doc in confluence_connector.retrieve_all_slim_docs_perm_sync():
        print(slim_doc)

    # Fetch all `Documents`.
    for doc in load_all_docs_from_checkpoint_connector(
        connector=confluence_connector,
        start=start,
        end=end,
    ):
        print(doc)
