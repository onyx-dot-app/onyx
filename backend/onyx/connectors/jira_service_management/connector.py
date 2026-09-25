import io
from typing import Any, ClassVar

from jira.resources import Issue

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import (
    ConnectorValidationError,
)
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import (
    JiraConnector,
    _perform_jql_search,
    build_jira_url,
    process_jira_issue,
)
from onyx.connectors.jira_service_management.utils import (
    JsmFieldMap,
    build_jsm_metadata,
    discover_jsm_fields,
    get_jsm_comment_strs,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    SlimDocument,
    TextSection,
)
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(JiraConnector):
    """Indexes all tickets from a specified Jira Service Management project.

    JSM is backed by the same Jira REST API as regular Jira, so this connector
    subclasses the Jira connector (checkpointed pagination, slim docs, hierarchy
    and permission sync all carry over) and specializes:

    - document source branding (``DocumentSource.JIRA_SERVICE_MANAGEMENT``)
    - comment handling: JSM internal agent notes (``jsdPublic`` comments) are
      excluded unless ``include_internal_comments`` is set, in which case they
      are tagged with an ``[Internal Note]`` prefix
    - JSM specific metadata: customer request type, organizations and SLA
      statuses, discovered by field name so no instance-specific field IDs are
      hard-coded
    - settings validation: a service desk project key is required and the
      project must be a JSM (``service_desk``) project
    """

    document_source: ClassVar[DocumentSource] = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
        include_internal_comments: bool = False,
        include_attachments: bool = False,
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
        self.include_internal_comments = include_internal_comments
        self.include_attachments = include_attachments
        self._jsm_field_map: JsmFieldMap | None = None
        # Ticket document IDs whose attachment listing failed this run.
        self._attachment_admission_failures: dict[str, Exception] = {}
        # Ticket document ID -> doc IDs of attachments that failed in the
        # main pass (download or content errors). The slim pass excludes
        # exactly these IDs so admitted IDs stay in exact parity with the
        # documents the main pass actually produced, without penalizing
        # healthy sibling attachments.
        self._failed_attachment_doc_ids: dict[str, set[str]] = {}

    @property
    def jsm_field_map(self) -> JsmFieldMap:
        """JSM field IDs, discovered lazily and cached for the connector's lifetime."""
        if self._jsm_field_map is None:
            self._jsm_field_map = discover_jsm_fields(self.jira_client)
        return self._jsm_field_map

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """JQL for the configured JSM project plus the poll window.

        Overrides the Jira connector version to always keep the project
        filter: this connector is scoped to a single service desk project, so
        a custom ``jql_query`` without its own project clause must not widen
        indexing to issues from other projects.

        Unquoted epoch-ms so Jira does not reinterpret naive datetimes in the
        API user's profile timezone.
        https://support.atlassian.com/jira-software-cloud/docs/jql-fields/#Updated
        """
        time_jql = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"
        base_jql = f"project = {self.quoted_jira_project}"
        if self.jql_query:
            return f"{base_jql} AND ({self.jql_query}) AND {time_jql}"
        return f"{base_jql} AND {time_jql}"

    def _process_issue(
        self,
        issue: Issue,
        parent_hierarchy_raw_node_id: str | None = None,
    ) -> Document | None:
        document = process_jira_issue(
            jira_base_url=self.jira_base,
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
            labels_to_skip=self.labels_to_skip,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
            source=self.document_source,
            comment_extractor=lambda issue: get_jsm_comment_strs(
                issue=issue,
                comment_email_blacklist=self.comment_email_blacklist,
                include_internal_comments=self.include_internal_comments,
            ),
        )
        if document is None:
            return None

        # Enrichment is best effort: a failure to extract JSM metadata should
        # not lose the ticket itself.
        try:
            document.metadata.update(build_jsm_metadata(issue, self.jsm_field_map))
        except Exception:
            logger.exception(
                "Failed to extract JSM metadata for %s; continuing without it.",
                issue.key,
            )
        return document

    def _fetch_issue_attachments(self, issue_key: str) -> list[Any]:
        """Fetch the attachment resources of an issue.

        The JQL search payload does not include the attachment field, so the
        attachment set is fetched with a dedicated per-issue call. Only
        reached when ``include_attachments`` is enabled, keeping the default
        path free of extra API traffic.
        """
        fetched = self.jira_client.issue(issue_key, fields="attachment")
        attachments = fetched.fields.attachment or []
        return list(attachments)

    def _process_issue_attachments(
        self,
        issue: Issue,
        parent_hierarchy_raw_node_id: str | None,
        ticket_document_id: str,
    ) -> list[Document | ConnectorFailure]:
        if not self.include_attachments:
            return []

        try:
            attachments = self._fetch_issue_attachments(issue.key)
        except Exception as e:
            # Preserve the ticket while making the unavailable attachment set
            # fatal to the later slim enumeration.
            logger.exception("Failed to list attachments for %s", issue.key)
            self._attachment_admission_failures[ticket_document_id] = e
            return [
                ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=f"{ticket_document_id}/attachments",
                        document_link=build_jira_url(self.jira_base, issue.key),
                    ),
                    failure_message=(
                        f"Failed to list attachments for JSM issue {issue.key}"
                    ),
                    exception=e,
                )
            ]

        # Download/convert every attachment first. Attachments that fail are
        # tracked per doc ID so the slim pass admits exactly the IDs that
        # produced a main-pass document (full/slim parity): extra slim docs
        # would become permanent ``chunk_count IS NULL`` rows, and excluding
        # only the failed IDs keeps healthy siblings unaffected.
        self._attachment_admission_failures.pop(ticket_document_id, None)
        outputs: list[Document | ConnectorFailure] = []
        failed_doc_ids: set[str] = set()
        for attachment in attachments:
            attachment_id = str(getattr(attachment, "id", "") or "")
            output = self._build_attachment_output(
                issue=issue,
                attachment=attachment,
                parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
                ticket_document_id=ticket_document_id,
            )
            if isinstance(output, ConnectorFailure):
                failed_doc_ids.add(f"{ticket_document_id}/attachment/{attachment_id}")
            outputs.append(output)
        if failed_doc_ids:
            self._failed_attachment_doc_ids[ticket_document_id] = failed_doc_ids
        else:
            self._failed_attachment_doc_ids.pop(ticket_document_id, None)
        return outputs

    def _build_attachment_output(
        self,
        issue: Issue,
        attachment: Any,
        parent_hierarchy_raw_node_id: str | None,
        ticket_document_id: str,
    ) -> Document | ConnectorFailure:
        """Download and convert a single attachment into a Document.

        Failures are isolated per attachment: they are reported as
        ConnectorFailure and never fail the ticket or sibling attachments.
        """
        filename = str(getattr(attachment, "filename", "") or "")
        attachment_id = str(getattr(attachment, "id", "") or "")
        doc_id = f"{ticket_document_id}/attachment/{attachment_id}"

        try:
            file_bytes = attachment.get()
            text = (
                extract_file_text(
                    io.BytesIO(file_bytes or b""),
                    file_name=filename or f"attachment-{attachment_id}",
                    break_on_unprocessable=False,
                )
                or ""
            )
        except Exception as e:
            logger.exception(
                "Failed to process attachment %s (%s) of %s",
                filename,
                attachment_id,
                issue.key,
            )
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=doc_id,
                    document_link=build_jira_url(self.jira_base, issue.key),
                ),
                failure_message=(
                    f"Failed to process attachment '{filename}' ({attachment_id}) "
                    f"of JSM issue {issue.key}"
                ),
                exception=e,
            )

        if not file_bytes:
            # Zero-length or undecodable-to-empty attachments: downloading
            # succeeded but there is no indexable content. Emitting a
            # contentless document would create a junk record, and admitting
            # the ID in the slim pass while skipping it here would break
            # full/slim parity — so fail it like any other processing error.
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=doc_id,
                    document_link=build_jira_url(self.jira_base, issue.key),
                ),
                failure_message=(
                    f"Attachment '{filename}' ({attachment_id}) of JSM issue "
                    f"{issue.key} is empty; skipping indexing"
                ),
            )

        sections = [
            TextSection(text=text, link=str(getattr(attachment, "content", "")))
        ]
        if not text:
            # Extraction produced nothing usable: same reasoning as above.
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=doc_id,
                    document_link=build_jira_url(self.jira_base, issue.key),
                ),
                failure_message=(
                    f"No extractable content in attachment '{filename}' "
                    f"({attachment_id}) of JSM issue {issue.key}"
                ),
            )

        return Document(
            id=doc_id,
            source=self.document_source,
            semantic_identifier=(
                f"{issue.key} attachment: {filename}"
                if filename
                else f"{issue.key} attachment {attachment_id}"
            ),
            sections=sections,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
            metadata={
                "jira_issue_key": issue.key,
                "attachment_filename": filename,
                "attachment_id": attachment_id,
            },
        )

    def _process_issue_attachments_slim(
        self,
        issue: Issue,
        parent_hierarchy_raw_node_id: str | None,
        ticket_document_id: str,
        include_permissions: bool = False,
        project_key: str | None = None,
    ) -> list[SlimDocument]:
        if not self.include_attachments:
            return []

        listing_error = self._attachment_admission_failures.get(ticket_document_id)
        if listing_error is not None:
            logger.error(
                "Attachment enumeration failed in the main pass for %s",
                issue.key,
            )
            raise listing_error
        failed_ids = self._failed_attachment_doc_ids.get(ticket_document_id, set())

        try:
            attachments = self._fetch_issue_attachments(issue.key)
        except Exception as e:
            logger.exception("Failed to list attachment slim docs for %s", issue.key)
            self._attachment_admission_failures[ticket_document_id] = e
            raise

        external_access = (
            self._get_project_permissions(project_key)
            if include_permissions and project_key
            else None
        )

        slim_docs: list[SlimDocument] = []
        for attachment in attachments:
            attachment_id = str(getattr(attachment, "id", "") or "")
            doc_id = f"{ticket_document_id}/attachment/{attachment_id}"
            if doc_id in failed_ids:
                # Failed in the main pass: no document exists for it, so
                # admitting the ID would create a chunk_count IS NULL row.
                continue
            created = str(getattr(attachment, "created", "") or "")
            slim_docs.append(
                SlimDocument(
                    # Must exactly match the main-pass attachment document ID
                    id=doc_id,
                    # Permission sync path: inherit the ticket's resolved
                    # project access so attachment permissions stay in sync
                    # with their parent ticket (generic_doc_sync requires it
                    # and upsert_document_external_perms replaces wholesale).
                    external_access=external_access,
                    parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
                    doc_created_at=time_str_to_utc(created) if created else None,
                )
            )
        return slim_docs

    @staticmethod
    def _best_effort_project_type(project: Any) -> str | None:
        # Direct attribute access (repo convention: no getattr); both
        # attributes are statically known on Jira project resources and the
        # caller handles the "not exposed by the instance" case.
        try:
            project_type = project.projectTypeKey
        except AttributeError:
            project_type = None
        if isinstance(project_type, str) and project_type:
            return project_type

        try:
            raw = project.raw
        except AttributeError:
            return None
        if isinstance(raw, dict):
            raw_type = raw.get("projectTypeKey")
            if isinstance(raw_type, str) and raw_type:
                return raw_type
        return None

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        # A JSM project key is mandatory; the general-purpose Jira connector is
        # the right tool for indexing everything a credential can access.
        if not self.jira_project or not self.jira_project.strip():
            raise ConnectorValidationError(
                "A Jira Service Management project key is required."
            )

        try:
            project = self.jira_client.project(self.jira_project)
        except Exception as e:
            self._handle_jira_connector_settings_error(e)
            raise  # _handle_jira_connector_settings_error always raises

        # Enforce that the project actually is a service desk project. Only
        # checked when the project type is exposed by the instance.
        project_type = self._best_effort_project_type(project)
        if project_type is not None and project_type != "service_desk":
            raise ConnectorValidationError(
                f"Project '{self.jira_project}' is a '{project_type}' project, but "
                "the Jira Service Management connector requires a service desk "
                "project (projectTypeKey == 'service_desk'). Use the Jira "
                "connector for traditional Jira projects."
            )

        # If a custom JQL query is set, validate it's valid
        if self.jql_query:
            try:
                next(
                    iter(
                        _perform_jql_search(
                            jira_client=self.jira_client,
                            jql=self.jql_query,
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

    from onyx.utils.variable_functionality import global_version
    from tests.daily.connectors.utils import load_all_from_connector

    # For connector permission testing, set EE to true.
    global_version.set_ee()

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_BASE_URL"],
        project_key=os.environ["JSM_PROJECT_KEY"],
        comment_email_blacklist=[],
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
