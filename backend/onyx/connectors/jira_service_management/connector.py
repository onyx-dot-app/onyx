"""Connector for Jira Service Management (JSM) projects.

Shares the Jira connector's JQL fetching, checkpointing and hierarchy
handling; adds JSM-specific metadata (customer request type, organizations,
request participants, SLA status), internal/public comment handling, and
optional attachment indexing.
"""

from collections.abc import Iterable
from io import BytesIO
from typing import Any, ClassVar

from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
)
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    time_str_to_utc,
)
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    is_tabular_file,
    tabular_file_to_sections,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import (
    JiraConnector,
    _perform_jql_search,
    process_jira_issue,
)
from onyx.connectors.jira_service_management.utils import (
    JsmFieldMap,
    build_jsm_attachment_doc_id,
    build_jsm_metadata,
    discover_jsm_fields,
    get_issue_attachments,
    get_jsm_comment_strs,
    is_jsm_attachment_admissible,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TabularSection,
    TextSection,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(JiraConnector):
    document_source: ClassVar[DocumentSource] = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        # if a ticket has one of the labels specified in this list, we will just
        # skip it. This is generally used to avoid indexing extra sensitive
        # tickets.
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        # Additional JQL filter, always combined with the project scope
        jql_query: str | None = None,
        scoped_token: bool = False,
        include_attachments: bool = False,
        # Whether to index agent-only internal notes in addition to
        # customer-visible comments
        include_internal_comments: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )
        self.include_attachments = include_attachments
        self.include_internal_comments = include_internal_comments
        self.allow_images = False
        self._jsm_field_map: JsmFieldMap | None = None

    @override
    def set_allow_images(self, value: bool) -> None:
        logger.info("Setting allow_images to %s.", value)
        self.allow_images = value

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """JSM is always scoped to its service desk project; a custom JQL
        filter is ANDed into that scope."""
        time_jql = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"
        base_jql = f"project = {self.quoted_jira_project}"
        if self.jql_query:
            base_jql = f"{base_jql} AND ({self.jql_query})"
        return f"{base_jql} AND {time_jql}"

    @property
    def _jsm_fields(self) -> JsmFieldMap:
        if self._jsm_field_map is None:
            self._jsm_field_map = discover_jsm_fields(self.jira_client)
        return self._jsm_field_map

    @override
    def _process_issue(
        self, issue: Issue, parent_hierarchy_raw_node_id: str | None
    ) -> Document | None:
        def _comment_extractor(issue: Issue) -> list[str]:
            return get_jsm_comment_strs(
                issue=issue,
                comment_email_blacklist=self.comment_email_blacklist,
                include_internal_comments=self.include_internal_comments,
            )

        document = process_jira_issue(
            jira_base_url=self.jira_base,
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
            labels_to_skip=self.labels_to_skip,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
            source=self.document_source,
            comment_extractor=_comment_extractor,
        )
        if document is None:
            return None

        jsm_metadata = build_jsm_metadata(issue, self._jsm_fields)
        if jsm_metadata:
            metadata = document.metadata or {}
            metadata.update(jsm_metadata)
            document.metadata = metadata
        return document

    @override
    def _issue_is_skipped(self, issue: Issue) -> bool:
        if not self.labels_to_skip:
            return False
        labels = issue.fields.labels or []
        return any(label in self.labels_to_skip for label in labels)

    def _download_attachment(self, attachment: dict[str, Any]) -> bytes | None:
        download_url = attachment.get("content")
        if not isinstance(download_url, str) or not download_url:
            logger.warning("JSM attachment has no content URL to download")
            return None
        try:
            response = self.jira_client._session.get(  # ty: ignore[unresolved-attribute]
                download_url, headers={"Accept": "application/octet-stream"}
            )
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.warning("Failed to download JSM attachment: %s", e)
            return None

    def _process_issue_attachment(
        self,
        issue: Issue,
        attachment: dict[str, Any],
        issue_document: Document,
    ) -> Document | None:
        """Build a Document for a single issue attachment. A failed download
        still produces a minimal stub document so the slim pass, which can
        only see attachment metadata, stays in sync with the indexed set.
        Returns None only when no usable content sections can be built."""
        attachment_doc_id = build_jsm_attachment_doc_id(self.jira_base, attachment)
        if attachment_doc_id is None:
            logger.warning("Skipping JSM attachment on %s with no usable id", issue.key)
            return None

        file_name = attachment.get("filename")
        file_name = file_name if isinstance(file_name, str) else "attachment"
        media_type = attachment.get("mimeType")
        media_type = media_type if isinstance(media_type, str) else ""

        sections: list[TextSection | ImageSection | TabularSection] = []
        raw_bytes = self._download_attachment(attachment)
        if raw_bytes is None:
            sections.append(
                TextSection(
                    link=attachment_doc_id,
                    text=f"Attachment {file_name} on {issue.key}",
                )
            )
        elif media_type in OnyxMimeTypes.IMAGE_MIME_TYPES:
            if not self.allow_images:
                return None
            image_section, _ = store_image_and_create_section(
                image_data=raw_bytes,
                file_id=str(attachment.get("id") or attachment_doc_id),
                display_name=file_name,
                link=attachment_doc_id,
                media_type=media_type,
                file_origin=FileOrigin.CONNECTOR,
            )
            sections.append(image_section)
        elif is_tabular_file(file_name) and self.raw_file_callback is not None:
            sections.extend(
                tabular_file_to_sections(
                    BytesIO(raw_bytes),
                    file_name=file_name,
                    stage=self.raw_file_callback,
                    link=attachment_doc_id,
                )
            )
        else:
            text = extract_file_text(
                file=BytesIO(raw_bytes),
                file_name=file_name,
                break_on_unprocessable=False,
            )
            if not text.strip():
                text = f"Attachment {file_name} on {issue.key}"
            sections.append(TextSection(link=attachment_doc_id, text=text))

        if not sections:
            return None

        metadata: dict[str, str | list[str]] = {
            "filename": file_name,
            "parent_issue": issue.key,
            "parent_issue_link": issue_document.id,
        }
        if media_type:
            metadata["mime_type"] = media_type
        size = attachment.get("size")
        if isinstance(size, int):
            metadata["size_bytes"] = str(size)

        primary_owners = []
        author = attachment.get("author")
        if isinstance(author, dict):
            display_name = author.get("displayName")
            email = author.get("emailAddress")
            if display_name or email:
                primary_owners.append(
                    BasicExpertInfo(display_name=display_name, email=email)
                )

        created = attachment.get("created")
        return Document(
            id=attachment_doc_id,
            sections=sections,
            source=self.document_source,
            semantic_identifier=f"{file_name} ({issue.key})",
            title=f"{file_name} on {issue.key}",
            doc_created_at=(
                time_str_to_utc(created) if isinstance(created, str) else None
            ),
            primary_owners=primary_owners or None,
            metadata=metadata,
            external_access=issue_document.external_access,
            parent_hierarchy_raw_node_id=issue_document.id,
        )

    @override
    def _iter_issue_attachment_docs(
        self, issue: Issue, document: Document
    ) -> Iterable[Document | HierarchyNode | ConnectorFailure]:
        if not self.include_attachments:
            return

        emitted_issue_node = False
        for attachment in get_issue_attachments(issue):
            if not is_jsm_attachment_admissible(attachment, self.allow_images):
                continue
            attachment_doc_id = build_jsm_attachment_doc_id(self.jira_base, attachment)
            if attachment_doc_id is None:
                continue

            if not emitted_issue_node:
                # The issue becomes a hierarchy node so its attachments hang
                # under it; raw_node_id matches the document id for the
                # document<->node link.
                yield HierarchyNode(
                    raw_node_id=document.id,
                    raw_parent_id=document.parent_hierarchy_raw_node_id,
                    display_name=document.semantic_identifier,
                    link=document.id,
                    node_type=HierarchyNodeType.PAGE,
                )
                emitted_issue_node = True

            try:
                attachment_doc = self._process_issue_attachment(
                    issue, attachment, document
                )
            except Exception as e:
                logger.exception("Failed to process JSM attachment on %s", issue.key)
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=attachment_doc_id,
                        document_link=document.id,
                    ),
                    failure_message=f"Failed to process JSM attachment: {e}",
                    exception=e,
                )
                continue

            if attachment_doc is not None:
                yield attachment_doc

    @override
    def _iter_issue_slim_attachments(
        self,
        issue: Issue,
        issue_doc_id: str,
        project_key: str,
        include_permissions: bool,
    ) -> Iterable[SlimDocument | HierarchyNode]:
        if not self.include_attachments:
            return

        emitted_issue_node = False
        for attachment in get_issue_attachments(issue):
            if not is_jsm_attachment_admissible(attachment, self.allow_images):
                continue
            attachment_doc_id = build_jsm_attachment_doc_id(self.jira_base, attachment)
            if attachment_doc_id is None:
                continue

            external_access = (
                self._get_project_permissions(project_key, add_prefix=False)
                if include_permissions
                else None
            )

            if not emitted_issue_node:
                yield HierarchyNode(
                    raw_node_id=issue_doc_id,
                    raw_parent_id=self._get_parent_hierarchy_raw_node_id(
                        issue, project_key
                    ),
                    display_name=issue.key,
                    link=issue_doc_id,
                    node_type=HierarchyNodeType.PAGE,
                    external_access=external_access,
                )
                emitted_issue_node = True

            created = attachment.get("created")
            yield SlimDocument(
                id=attachment_doc_id,
                external_access=external_access,
                parent_hierarchy_raw_node_id=issue_doc_id,
                doc_created_at=(
                    time_str_to_utc(created) if isinstance(created, str) else None
                ),
            )

    @override
    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        if not self.jira_project:
            raise ConnectorValidationError(
                "A Jira Service Management project key is required for this connector."
            )

        try:
            project = self.jira_client.project(self.jira_project)
        except Exception as e:
            self._handle_jira_connector_settings_error(e)

        project_raw = project.raw if isinstance(project.raw, dict) else {}
        project_type = project_raw.get("projectTypeKey")
        if project_type != "service_desk":
            raise ConnectorValidationError(
                f"Project {self.jira_project} is not a Jira Service Management "
                "(service desk) project. Use the Jira connector for classic "
                "Jira projects."
            )

        # Validate the effective (project-scoped) JQL, which also catches
        # syntax errors in the optional custom filter.
        try:
            next(
                iter(
                    _perform_jql_search(
                        jira_client=self.jira_client,
                        jql=self._get_jql_query(0, 0),
                        start=0,
                        max_results=1,
                        all_issue_ids=[],
                    )
                ),
                None,
            )
        except Exception as e:
            self._handle_jira_connector_settings_error(e)


if __name__ == "__main__":
    import os
    from datetime import datetime

    from tests.daily.connectors.utils import load_all_from_connector

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ["JIRA_SERVICE_MANAGEMENT_PROJECT_KEY"],
        comment_email_blacklist=[],
        include_attachments=True,
    )

    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )

    start = 0
    end = datetime.now().timestamp()

    for slim_doc in connector.retrieve_all_slim_docs_perm_sync(
        start=start,
        end=end,
    ):
        print(slim_doc)

    for doc in load_all_from_connector(
        connector=connector,
        start=start,
        end=end,
    ).documents:
        print(doc)
