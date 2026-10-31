from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import JIRA_CONNECTOR_MAX_TICKET_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.jira_service_management.client import (
    JiraServiceManagementClient,
)
from onyx.connectors.jira_service_management.client import (
    JiraServiceManagementClientError,
)
from onyx.connectors.jira_service_management.models import (
    JiraServiceManagementCheckpoint,
)
from onyx.connectors.jira_service_management.models import JsmAttachment
from onyx.connectors.jira_service_management.models import JsmChangelogEntry
from onyx.connectors.jira_service_management.models import JsmComment
from onyx.connectors.jira_service_management.models import ServiceDeskInfo
from onyx.connectors.jira_service_management.models import ServiceDeskQueueInfo
from onyx.connectors.jira_service_management.models import SlaMetric
from onyx.connectors.jira_service_management.utils import (
    best_effort_basic_expert_info,
)
from onyx.connectors.jira_service_management.utils import build_jsm_browse_url
from onyx.connectors.jira_service_management.utils import (
    extract_attachments_from_issue,
)
from onyx.connectors.jira_service_management.utils import (
    extract_attachments_from_jsm_payload,
)
from onyx.connectors.jira_service_management.utils import (
    extract_changelog_entries,
)
from onyx.connectors.jira_service_management.utils import (
    extract_comments_from_issue_fields,
)
from onyx.connectors.jira_service_management.utils import (
    extract_comments_from_jsm_payload,
)
from onyx.connectors.jira_service_management.utils import extract_rich_text
from onyx.connectors.jira_service_management.utils import (
    extract_sla_from_issue_fields,
)
from onyx.connectors.jira_service_management.utils import (
    extract_sla_metrics_from_jsm_payload,
)
from onyx.connectors.jira_service_management.utils import (
    format_changelog_section,
)
from onyx.connectors.jira_service_management.utils import (
    format_comments_section,
)
from onyx.connectors.jira_service_management.utils import format_sla_section
from onyx.connectors.jira_service_management.utils import parse_jsm_datetime
from onyx.connectors.jira_service_management.utils import populate_sla_metadata
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.db.enums import HierarchyNodeType
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_TEXT_ATTACHMENT_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
    "application/csv",
)
_MAX_ATTACHMENT_BYTES = 1024 * 1024  # 1 MiB for text attachment extraction


def _escape_jql_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _seconds_to_jql_str(seconds: SecondsSinceUnixEpoch) -> str:
    return str(int(seconds * 1000))


class JiraServiceManagementConnector(
    CheckpointedConnector[JiraServiceManagementCheckpoint],
    PollConnector,
    LoadConnector,
    SlimConnector,
):
    """Connector for Atlassian Jira Service Management (JSM) Cloud and Data Center."""

    def __init__(
        self,
        jira_service_management_base_url: str,
        project_key: str | None = None,
        service_desk_ids: list[str] | None = None,
        queue_ids: list[str] | None = None,
        request_types: list[str] | None = None,
        jql_query: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        include_internal_comments: bool = True,
        include_sla: bool = True,
        include_changelog: bool = True,
        include_attachments: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,
        scoped_token: bool = False,
    ) -> None:
        super().__init__()
        self.jira_service_management_base_url = (
            jira_service_management_base_url.rstrip("/")
        )
        self.project_key = project_key.strip() if project_key else None
        self.service_desk_ids = [
            s.strip() for s in (service_desk_ids or []) if s and s.strip()
        ]
        self.queue_ids = [q.strip() for q in (queue_ids or []) if q and q.strip()]
        self.request_types = [
            r.strip() for r in (request_types or []) if r and r.strip()
        ]
        self.jql_query = jql_query.strip() if jql_query else None
        self.comment_email_blacklist = set(
            e.strip().lower()
            for e in (comment_email_blacklist or [])
            if e and e.strip()
        )
        self.labels_to_skip = set(labels_to_skip or [])
        self.include_internal_comments = include_internal_comments
        self.include_sla = include_sla
        self.include_changelog = include_changelog
        self.include_attachments = include_attachments
        self.batch_size = max(1, batch_size)
        self.scoped_token = scoped_token

        self._client: JiraServiceManagementClient | None = None
        self._service_desks_by_id: dict[str, ServiceDeskInfo] = {}
        self._service_desks_by_project_key: dict[str, ServiceDeskInfo] = {}
        self._discovery_done: bool = False

    # -------------------------------------------------------------------------
    # Credentials & Validation
    # -------------------------------------------------------------------------

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        api_token = (
            credentials.get("jira_service_management_api_token")
            or credentials.get("jira_api_token")
        )
        if not api_token or not str(api_token).strip():
            raise ConnectorValidationError(
                "Missing Jira Service Management API token (`jira_api_token`)."
            )

        user_email = (
            credentials.get("jira_service_management_user_email")
            or credentials.get("jira_user_email")
        )
        user_email_str = (
            str(user_email).strip()
            if user_email and str(user_email).strip()
            else None
        )
        api_version = credentials.get("jira_api_version")
        api_version_str = (
            str(api_version).strip()
            if api_version and str(api_version).strip()
            else None
        )

        if not self.jira_service_management_base_url or not self.jira_service_management_base_url.startswith("https://"):
            raise ConnectorValidationError(
                "Jira Service Management Base URL must start with 'https://'."
            )
        self._client = JiraServiceManagementClient(
            base_url=self.jira_service_management_base_url,
            api_token=str(api_token).strip(),
            user_email=user_email_str,
            scoped_token=self.scoped_token,
            api_version=api_version_str,
        )
        self._discovery_done = False
        return None

    def set_credentials_provider(
        self, credentials_provider: OnyxStaticCredentialsProvider
    ) -> None:
        super().set_credentials_provider(credentials_provider)
        if credentials_provider:
            self.load_credentials(credentials_provider.get_credentials())

    @property
    def client(self) -> JiraServiceManagementClient:
        if self._client is None:
            if self.credentials_provider is not None:
                self.load_credentials(self.credentials_provider.get_credentials())
            if self._client is None:
                raise RuntimeError(
                    "JiraServiceManagementConnector client not initialized; call load_credentials first."
                )
        return self._client

    def validate_connector_settings(self) -> None:
        if not self.jira_service_management_base_url or not self.jira_service_management_base_url.startswith("https://"):
            raise ConnectorValidationError(
                "Jira Service Management Base URL must start with 'https://'."
            )

        try:
            # Verify basic connectivity via JSM /rest/servicedeskapi/info or Jira /myself
            try:
                self.client.get_service_desk_info()
            except JiraServiceManagementClientError as exc:
                if exc.status_code in (401, 403):
                    raise
                self.client.get_myself()

            if self.jql_query:
                self.client.search_jql_page(
                    jql=self.jql_query,
                    fields=["summary"],
                    max_results=1,
                )
                return

            self._discover_service_desks()

            if self.service_desk_ids:
                for sd_id in self.service_desk_ids:
                    if sd_id not in self._service_desks_by_id:
                        try:
                            raw_sd = self.client.get_service_desk(sd_id)
                            info = self._parse_service_desk_info(raw_sd)
                            if info:
                                self._register_service_desk(info)
                        except JiraServiceManagementClientError as exc:
                            if exc.status_code == 404:
                                raise ConnectorValidationError(
                                    f"Service desk with ID '{sd_id}' was not found."
                                ) from exc
                            raise

            if self.project_key:
                # Verify project_key exists either as a discovered service desk or via JQL
                if self.project_key.upper() not in self._service_desks_by_project_key:
                    self.client.search_jql_page(
                        jql=f"project = {_escape_jql_string(self.project_key)}",
                        fields=["summary"],
                        max_results=1,
                    )

            if self.queue_ids:
                target_desks = self._resolve_target_service_desk_ids()
                if not target_desks:
                    raise ConnectorValidationError(
                        "When specifying queue_ids, at least one valid Service Desk or project_key must be accessible."
                    )
                found_queues: set[str] = set()
                for sd_id in target_desks:
                    for raw_q in self.client.list_queues(sd_id):
                        q_id = str(raw_q.get("id", "")).strip()
                        if q_id:
                            found_queues.add(q_id)
                missing = [q for q in self.queue_ids if q not in found_queues]
                if missing:
                    raise ConnectorValidationError(
                        f"Queue ID(s) not found in target service desk(s): {', '.join(missing)}"
                    )

        except ConnectorValidationError:
            raise
        except JiraServiceManagementClientError as exc:
            if exc.status_code == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Jira Service Management credentials (HTTP 401)."
                ) from exc
            if exc.status_code == 403:
                raise InsufficientPermissionsError(
                    "Insufficient permissions to access Jira Service Management (HTTP 403)."
                ) from exc
            if exc.status_code == 400:
                raise ConnectorValidationError(
                    f"Invalid Jira Service Management configuration or query: {exc}"
                ) from exc
            if exc.status_code == 404:
                raise ConnectorValidationError(
                    f"Jira Service Management resource not found: {exc}"
                ) from exc
            raise UnexpectedValidationError(
                f"Failed to validate Jira Service Management connector: {exc}"
            ) from exc
        except Exception as exc:
            raise UnexpectedValidationError(
                f"Unexpected error validating Jira Service Management connector: {exc}"
            ) from exc

    # -------------------------------------------------------------------------
    # Service Desk & Queue Metadata Discovery
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_service_desk_info(raw: dict[str, Any]) -> ServiceDeskInfo | None:
        sd_id = raw.get("id")
        if sd_id is None:
            return None
        project_key = str(raw.get("projectKey") or "").strip().upper()
        project_name = str(raw.get("projectName") or project_key or f"Desk {sd_id}").strip()
        project_id = str(raw.get("projectId")) if raw.get("projectId") is not None else None
        portal_url: str | None = None
        links = raw.get("_links")
        if isinstance(links, dict):
            portal_url = links.get("portal") or links.get("self")
        return ServiceDeskInfo(
            id=str(sd_id).strip(),
            project_id=project_id,
            project_name=project_name,
            project_key=project_key,
            portal_url=portal_url,
        )

    def _register_service_desk(self, info: ServiceDeskInfo) -> None:
        self._service_desks_by_id[info.id] = info
        if info.project_key:
            self._service_desks_by_project_key[info.project_key.upper()] = info

    def _discover_service_desks(self) -> None:
        if self._discovery_done:
            return
        for raw in self.client.list_service_desks():
            info = self._parse_service_desk_info(raw)
            if info:
                self._register_service_desk(info)
        self._discovery_done = True

    def _resolve_target_service_desk_ids(self) -> list[str]:
        self._discover_service_desks()
        if self.service_desk_ids:
            return list(self.service_desk_ids)
        if self.project_key:
            sd = self._service_desks_by_project_key.get(self.project_key.upper())
            if sd:
                return [sd.id]
        return list(self._service_desks_by_id.keys())

    def _resolve_queues_to_fetch(self) -> list[ServiceDeskQueueInfo]:
        """Resolve explicit queue_ids across target service desks."""
        if not self.queue_ids:
            return []
        target_desk_ids = self._resolve_target_service_desk_ids()
        wanted = set(self.queue_ids)
        queues: list[ServiceDeskQueueInfo] = []
        for sd_id in target_desk_ids:
            raw_queues = self.client.list_queues(sd_id)
            for raw_q in raw_queues:
                q_id = str(raw_q.get("id", "")).strip()
                if q_id in wanted:
                    queues.append(
                        ServiceDeskQueueInfo(
                            id=q_id,
                            name=str(raw_q.get("name") or f"Queue {q_id}"),
                            jql=raw_q.get("jql"),
                            issue_count=raw_q.get("issueCount"),
                            service_desk_id=sd_id,
                        )
                    )
        return queues

    # -------------------------------------------------------------------------
    # JQL Construction
    # -------------------------------------------------------------------------

    def build_jql_query(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> str:
        """Build the effective JQL query from config and optional poll window."""
        clauses: list[str] = []

        if self.jql_query:
            # Strip trailing ORDER BY from custom JQL if we need to append time window clauses
            base_jql = self.jql_query.strip()
            order_by_clause = ""
            upper_jql = base_jql.upper()
            order_idx = upper_jql.rfind(" ORDER BY ")
            if order_idx != -1:
                order_by_clause = base_jql[order_idx:].strip()
                base_jql = base_jql[:order_idx].strip()

            if base_jql:
                clauses.append(f"({base_jql})")
            if start is not None:
                clauses.append(f"updated >= {_seconds_to_jql_str(start)}")
            if end is not None:
                clauses.append(f"updated <= {_seconds_to_jql_str(end)}")

            combined = " AND ".join(clauses)
            if order_by_clause:
                return f"{combined} {order_by_clause}".strip()
            return f"{combined} ORDER BY updated ASC, key ASC".strip()

        self._discover_service_desks()

        project_keys: list[str] = []
        if self.project_key:
            project_keys.append(self.project_key)
        if self.service_desk_ids:
            for sd_id in self.service_desk_ids:
                sd = self._service_desks_by_id.get(sd_id)
                if sd is None:
                    raw_sd = self.client.get_service_desk(sd_id)
                    sd = self._parse_service_desk_info(raw_sd)
                    if sd:
                        self._register_service_desk(sd)
                if not sd or not sd.project_key:
                    raise ConnectorValidationError(
                        f"Could not resolve project key for configured service_desk_id '{sd_id}'."
                    )
                if sd.project_key not in project_keys:
                    project_keys.append(sd.project_key)

        if len(project_keys) == 1:
            clauses.append(f"project = {_escape_jql_string(project_keys[0])}")
        elif len(project_keys) > 1:
            quoted_keys = ", ".join(_escape_jql_string(k) for k in project_keys)
            clauses.append(f"project IN ({quoted_keys})")
        else:
            # Default to Service Desk project type if no specific project/desk is configured
            clauses.append('projectType = "service_desk"')

        if self.request_types:
            if len(self.request_types) == 1:
                clauses.append(
                    f'"Customer Request Type" = {_escape_jql_string(self.request_types[0])}'
                )
            else:
                quoted_rts = ", ".join(
                    _escape_jql_string(rt) for rt in self.request_types
                )
                clauses.append(f'"Customer Request Type" IN ({quoted_rts})')

        if start is not None:
            clauses.append(f"updated >= {_seconds_to_jql_str(start)}")
        if end is not None:
            clauses.append(f"updated <= {_seconds_to_jql_str(end)}")

        where_part = " AND ".join(clauses)
        if where_part:
            return f"{where_part} ORDER BY updated ASC, key ASC"
        return "ORDER BY updated ASC, key ASC"

    # -------------------------------------------------------------------------
    # Ticket / Request -> Onyx Document Conversion
    # -------------------------------------------------------------------------

    def _should_skip_issue(self, issue: dict[str, Any]) -> str | None:
        """Return a reason string if the issue should be skipped, else None."""
        if not self.labels_to_skip:
            return None
        fields = issue.get("fields")
        if not isinstance(fields, dict):
            fields = {}
            issue["fields"] = fields
        labels = fields.get("labels")
        if not isinstance(labels, list):
            issue_key = str(issue.get("key") or issue.get("id") or "").strip()
            if not issue_key:
                return "Skipped because issue key and labels could not be established"
            fetched = self.client.get_issue(issue_key, fields="labels")
            fetched_fields = fetched.get("fields") if isinstance(fetched.get("fields"), dict) else {}
            labels = fetched_fields.get("labels")
            if not isinstance(labels, list):
                return f"Skipped {issue_key} because authoritative labels could not be retrieved"
            fields["labels"] = labels
        matched = [
            str(lbl) for lbl in labels if str(lbl) in self.labels_to_skip
        ]
        if matched:
            return f"Skipped due to label(s): {', '.join(matched)}"
        return None

    def _resolve_issue_request_type_name(
        self,
        issue: dict[str, Any],
        jsm_request: dict[str, Any] | None = None,
    ) -> str | None:
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        if jsm_request and isinstance(jsm_request.get("requestType"), dict):
            name = jsm_request["requestType"].get("name")
            if name:
                return str(name)
        for val in fields.values():
            if isinstance(val, dict) and isinstance(val.get("requestType"), dict):
                name = val["requestType"].get("name")
                if name:
                    return str(name)
        issue_key = str(issue.get("key") or issue.get("id") or "").strip()
        if issue_key and jsm_request is None:
            try:
                req = self.client.get_customer_request(issue_key, expand=["requestType"])
                if isinstance(req.get("requestType"), dict) and req["requestType"].get("name"):
                    return str(req["requestType"]["name"])
            except JiraServiceManagementClientError as exc:
                if exc.status_code != 404:
                    raise
        return None

    def _build_hierarchy_node(
        self,
        service_desk: ServiceDeskInfo | None,
        project_key: str | None,
        project_name: str | None,
    ) -> HierarchyNode | None:
        key = (
            service_desk.project_key
            if service_desk and service_desk.project_key
            else (project_key or "")
        ).strip()
        if not key and service_desk:
            key = f"SD-{service_desk.id}"
        if not key:
            return None

        display_name = (
            service_desk.project_name
            if service_desk and service_desk.project_name
            else (project_name or key)
        )
        link = (
            service_desk.portal_url
            if service_desk and service_desk.portal_url
            else f"{self.jira_service_management_base_url}/projects/{key}"
        )
        return HierarchyNode(
            raw_node_id=key,
            display_name=display_name,
            link=link,
            node_type=HierarchyNodeType.PROJECT,
        )

    def _fetch_sla_metrics(
        self,
        issue_key: str,
        issue_fields: dict[str, Any],
        jsm_request: dict[str, Any] | None,
    ) -> list[SlaMetric]:
        if not self.include_sla:
            return []

        # 1. Check if JSM customer request payload already expanded SLA
        if jsm_request and isinstance(jsm_request.get("sla"), dict):
            metrics = extract_sla_metrics_from_jsm_payload(
                jsm_request["sla"].get("values")
            )
            if metrics:
                return metrics

        # 2. Query dedicated JSM SLA endpoint: GET /rest/servicedeskapi/request/{issueKey}/sla
        try:
            raw_slas = self.client.get_request_sla(issue_key)
            metrics = extract_sla_metrics_from_jsm_payload(raw_slas)
            if metrics:
                return metrics
        except JiraServiceManagementClientError as exc:
            logger.debug(
                f"SLA endpoint unavailable for {issue_key} ({exc.status_code}), falling back to issue fields"
            )

        # 3. Fallback to SLA custom fields on the Jira issue
        return extract_sla_from_issue_fields(issue_fields)

    def _fetch_comments(
        self,
        issue_key: str,
        issue_fields: dict[str, Any],
        jsm_request: dict[str, Any] | None,
    ) -> list[JsmComment]:
        # 1. Check expanded comments in JSM request payload if present
        if jsm_request and isinstance(jsm_request.get("comment"), dict):
            comments = extract_comments_from_jsm_payload(
                jsm_request["comment"].get("values"),
                include_internal=self.include_internal_comments,
                email_blacklist=self.comment_email_blacklist,
            )
            if comments:
                return comments

        # 2. Query JSM request comment endpoint (supports explicit public/internal visibility)
        try:
            raw_comments = self.client.get_request_comments(
                issue_key,
                public=True,
                internal=self.include_internal_comments,
            )
            comments = extract_comments_from_jsm_payload(
                raw_comments,
                include_internal=self.include_internal_comments,
                email_blacklist=self.comment_email_blacklist,
            )
            if comments:
                return comments
        except JiraServiceManagementClientError as exc:
            logger.debug(
                f"JSM comment endpoint unavailable for {issue_key} ({exc.status_code}), falling back to issue fields"
            )

        # 3. Fallback to Jira issue fields.comment.comments
        return extract_comments_from_issue_fields(
            issue_fields,
            include_internal=self.include_internal_comments,
            email_blacklist=self.comment_email_blacklist,
        )

    def _fetch_changelog(
        self,
        issue_key: str,
        issue: dict[str, Any],
    ) -> list[JsmChangelogEntry]:
        if not self.include_changelog:
            return []

        changelog_block = issue.get("changelog")
        if isinstance(changelog_block, dict) and isinstance(
            changelog_block.get("histories"), list
        ):
            entries = extract_changelog_entries(changelog_block["histories"])
            if entries:
                return entries

        try:
            raw_histories = self.client.get_issue_changelog(issue_key)
            return extract_changelog_entries(raw_histories)
        except JiraServiceManagementClientError as exc:
            logger.debug(f"Could not fetch changelog for {issue_key}: {exc}")
            return []

    def _fetch_attachments(
        self,
        issue_key: str,
        issue_fields: dict[str, Any],
        jsm_request: dict[str, Any] | None,
    ) -> list[JsmAttachment]:
        if not self.include_attachments:
            return []

        attachments = extract_attachments_from_issue(issue_fields)
        if not attachments and jsm_request and isinstance(
            jsm_request.get("attachment"), dict
        ):
            attachments = extract_attachments_from_jsm_payload(
                jsm_request["attachment"].get("values")
            )
        if not attachments:
            try:
                raw_atts = self.client.get_request_attachments(issue_key)
                attachments = extract_attachments_from_jsm_payload(raw_atts)
            except JiraServiceManagementClientError as exc:
                logger.debug(f"Could not fetch attachments for {issue_key}: {exc}")
                return []

        # Attempt to download text content for small text-based attachments
        for att in attachments:
            if not att.content_url:
                continue
            if att.size and att.size > _MAX_ATTACHMENT_BYTES:
                continue
            mime = (att.mime_type or "").lower()
            is_text_file = any(
                mime.startswith(prefix) for prefix in _TEXT_ATTACHMENT_MIME_PREFIXES
            ) or att.filename.lower().endswith(
                (".txt", ".md", ".log", ".json", ".yaml", ".yml", ".csv")
            )
            if is_text_file:
                raw_bytes = self.client.download_attachment(
                    att.content_url,
                    max_size_bytes=_MAX_ATTACHMENT_BYTES,
                )
                if raw_bytes:
                    try:
                        att.extracted_text = raw_bytes.decode(
                            "utf-8", errors="replace"
                        ).strip()
                    except Exception:
                        pass
        return attachments

    def _convert_issue_to_document(
        self,
        issue: dict[str, Any],
        jsm_request: dict[str, Any] | None = None,
        queue_info: ServiceDeskQueueInfo | None = None,
    ) -> Document | None:
        issue_key = str(
            issue.get("key")
            or (jsm_request or {}).get("issueKey")
            or issue.get("id")
            or ""
        ).strip()
        if not issue_key:
            return None

        fields: dict[str, Any] = (
            issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        )
        rendered_fields: dict[str, Any] = (
            issue.get("renderedFields")
            if isinstance(issue.get("renderedFields"), dict)
            else {}
        )

        # Enrich with JSM request payload if available or fetch if fields are minimal
        if jsm_request is None:
            try:
                jsm_request = self.client.get_customer_request(
                    issue_key,
                    expand=["serviceDesk", "requestType", "participant", "status", "sla"],
                )
            except JiraServiceManagementClientError:
                jsm_request = None

        # Extract core fields
        summary = str(fields.get("summary") or "").strip()
        description = extract_rich_text(
            fields.get("description") or rendered_fields.get("description")
        )

        # Fallback to JSM requestFieldValues if summary/description weren't in Jira fields
        if jsm_request:
            req_field_values = jsm_request.get("requestFieldValues")
            if isinstance(req_field_values, list):
                for rfv in req_field_values:
                    if not isinstance(rfv, dict):
                        continue
                    field_id = rfv.get("fieldId")
                    val = rfv.get("value") or rfv.get("renderedValue")
                    if field_id == "summary" and not summary and val:
                        summary = extract_rich_text(val)
                    elif field_id == "description" and not description and val:
                        description = extract_rich_text(val)

        if not summary:
            summary = issue_key

        # Project & Service Desk resolution
        project_obj = fields.get("project") if isinstance(fields.get("project"), dict) else {}
        project_key = str(project_obj.get("key") or self.project_key or "").strip()
        project_name = str(project_obj.get("name") or project_key or "").strip()

        service_desk_id: str | None = None
        if jsm_request and jsm_request.get("serviceDeskId") is not None:
            service_desk_id = str(jsm_request.get("serviceDeskId"))
        elif queue_info and queue_info.service_desk_id:
            service_desk_id = queue_info.service_desk_id

        service_desk: ServiceDeskInfo | None = None
        if service_desk_id and service_desk_id in self._service_desks_by_id:
            service_desk = self._service_desks_by_id[service_desk_id]
        elif project_key and project_key.upper() in self._service_desks_by_project_key:
            service_desk = self._service_desks_by_project_key[project_key.upper()]
            if not service_desk_id:
                service_desk_id = service_desk.id

        if not project_key and service_desk:
            project_key = service_desk.project_key
        if not project_name and service_desk:
            project_name = service_desk.project_name

        # Request Type, Status, Priority, Issue Type, Resolution
        request_type_name: str | None = None
        if jsm_request:
            rt_obj = jsm_request.get("requestType")
            if isinstance(rt_obj, dict):
                request_type_name = rt_obj.get("name")
        if not request_type_name:
            # Check Jira customfield for Customer Request Type
            for val in fields.values():
                if isinstance(val, dict) and isinstance(val.get("requestType"), dict):
                    request_type_name = val["requestType"].get("name")
                    if not service_desk_id and val.get("serviceDeskId") is not None:
                        service_desk_id = str(val.get("serviceDeskId"))
                    break

        # Filter by configured request_types if set and we matched via queue or fallback
        if self.request_types and not self.jql_query:
            normalized_wanted = {rt.lower() for rt in self.request_types}
            if not request_type_name or request_type_name.lower() not in normalized_wanted:
                return None

        status_name: str | None = None
        status_category: str | None = None
        status_obj = fields.get("status")
        if isinstance(status_obj, dict):
            status_name = status_obj.get("name")
            cat_obj = status_obj.get("statusCategory")
            if isinstance(cat_obj, dict):
                status_category = cat_obj.get("name")
        if not status_name and jsm_request:
            curr_status = jsm_request.get("currentStatus")
            if isinstance(curr_status, dict):
                status_name = curr_status.get("status")
                status_category = curr_status.get("statusCategory")

        priority_obj = fields.get("priority")
        priority_name = (
            priority_obj.get("name") if isinstance(priority_obj, dict) else None
        )

        issuetype_obj = fields.get("issuetype")
        issue_type_name = (
            issuetype_obj.get("name") if isinstance(issuetype_obj, dict) else None
        )

        resolution_obj = fields.get("resolution")
        resolution_name = (
            resolution_obj.get("name") if isinstance(resolution_obj, dict) else None
        )

        # People: Reporter, Assignee, Creator, Request Participants, Organizations
        reporter_raw = fields.get("reporter") or (
            jsm_request.get("reporter") if jsm_request else None
        )
        assignee_raw = fields.get("assignee")
        creator_raw = fields.get("creator")

        reporter_info = best_effort_basic_expert_info(reporter_raw)
        assignee_info = best_effort_basic_expert_info(assignee_raw)
        creator_info = best_effort_basic_expert_info(creator_raw)

        primary_owners = [
            info for info in [assignee_info, reporter_info] if info is not None
        ]
        secondary_owners = [
            info for info in [creator_info] if info is not None and info not in primary_owners
        ]

        participants_names: list[str] = []
        if jsm_request and isinstance(jsm_request.get("participants"), dict):
            raw_parts = jsm_request["participants"].get("values")
            if isinstance(raw_parts, list):
                for part in raw_parts:
                    p_info = best_effort_basic_expert_info(part)
                    if p_info:
                        if p_info not in primary_owners and p_info not in secondary_owners:
                            secondary_owners.append(p_info)
                        label = p_info.display_name or p_info.email
                        if label:
                            participants_names.append(label)

        organizations: list[str] = []
        for field_val in fields.values():
            if isinstance(field_val, list) and field_val and all(
                isinstance(item, dict) and "name" in item and "id" in item
                for item in field_val
            ):
                # JSM Organizations customfield has [{"id": "1", "name": "Acme Corp"}]
                pass
        if jsm_request and isinstance(jsm_request.get("organizations"), dict):
            org_vals = jsm_request["organizations"].get("values")
            if isinstance(org_vals, list):
                organizations.extend(
                    str(o.get("name")).strip()
                    for o in org_vals
                    if isinstance(o, dict) and o.get("name")
                )

        labels = [
            str(lbl).strip()
            for lbl in (fields.get("labels") or [])
            if lbl and str(lbl).strip()
        ]
        components = [
            str(comp.get("name")).strip()
            for comp in (fields.get("components") or [])
            if isinstance(comp, dict) and comp.get("name")
        ]

        # Timestamps
        updated_dt = parse_jsm_datetime(
            fields.get("updated")
            or (jsm_request.get("currentStatus", {}).get("statusDate") if jsm_request and isinstance(jsm_request.get("currentStatus"), dict) else None)
            or (jsm_request.get("createdDate") if jsm_request else None)
        )
        created_dt = parse_jsm_datetime(
            fields.get("created")
            or (jsm_request.get("createdDate") if jsm_request else None)
        )

        # Canonical link & ID
        browse_url = build_jsm_browse_url(
            self.jira_service_management_base_url, issue_key
        )

        # Fetch SLA, Comments, Changelog, Attachments
        sla_metrics = self._fetch_sla_metrics(issue_key, fields, jsm_request)
        comments = self._fetch_comments(issue_key, fields, jsm_request)
        changelog_entries = self._fetch_changelog(issue_key, issue)
        attachments = self._fetch_attachments(issue_key, fields, jsm_request)

        # Build Document Sections
        sections: list[TextSection] = []

        # Section 1: Ticket Overview & Description
        overview_lines = [f"Request: {issue_key} - {summary}"]
        if service_desk:
            overview_lines.append(
                f"Service Desk: {service_desk.project_name} ({service_desk.project_key or service_desk.id})"
            )
        elif project_name or project_key:
            overview_lines.append(f"Project: {project_name or project_key}")
        if queue_info:
            overview_lines.append(f"Queue: {queue_info.name} (ID: {queue_info.id})")
        if request_type_name:
            overview_lines.append(f"Request Type: {request_type_name}")
        if issue_type_name:
            overview_lines.append(f"Issue Type: {issue_type_name}")
        if status_name:
            status_line = f"Status: {status_name}"
            if status_category:
                status_line += f" ({status_category})"
            overview_lines.append(status_line)
        if priority_name:
            overview_lines.append(f"Priority: {priority_name}")
        if resolution_name:
            overview_lines.append(f"Resolution: {resolution_name}")
        if reporter_info:
            overview_lines.append(
                f"Reporter: {reporter_info.display_name or reporter_info.email}"
            )
        if assignee_info:
            overview_lines.append(
                f"Assignee: {assignee_info.display_name or assignee_info.email}"
            )
        if organizations:
            overview_lines.append(f"Organizations: {', '.join(organizations)}")
        if participants_names:
            overview_lines.append(
                f"Request Participants: {', '.join(participants_names)}"
            )
        if labels:
            overview_lines.append(f"Labels: {', '.join(labels)}")
        if components:
            overview_lines.append(f"Components: {', '.join(components)}")
        if created_dt:
            overview_lines.append(f"Created: {created_dt.isoformat()}")
        if updated_dt:
            overview_lines.append(f"Updated: {updated_dt.isoformat()}")

        if description:
            overview_lines.append("")
            overview_lines.append("Description:")
            overview_lines.append(description)

        sections.append(
            TextSection(
                link=browse_url,
                text="\n".join(overview_lines).strip(),
            )
        )

        # Section 2: SLA Metrics
        sla_text = format_sla_section(sla_metrics)
        if sla_text:
            sections.append(
                TextSection(
                    link=browse_url,
                    text=sla_text,
                )
            )

        # Section 3: Comments (Public & Internal)
        comments_text = format_comments_section(comments)
        if comments_text:
            sections.append(
                TextSection(
                    link=browse_url,
                    text=comments_text,
                )
            )

        # Section 4: Changelog / Status History
        changelog_text = format_changelog_section(changelog_entries)
        if changelog_text:
            sections.append(
                TextSection(
                    link=browse_url,
                    text=changelog_text,
                )
            )

        # Section 5: Attachments
        if attachments:
            att_lines = ["Attachments:"]
            for att in attachments:
                att_header = f"- {att.filename}"
                details: list[str] = []
                if att.mime_type:
                    details.append(att.mime_type)
                if att.size is not None:
                    details.append(f"{att.size} bytes")
                if att.author:
                    details.append(f"uploaded by {att.author}")
                if details:
                    att_header += f" ({', '.join(details)})"
                att_lines.append(att_header)
                if att.extracted_text:
                    att_lines.append(f"  Content:\n{att.extracted_text}")
            sections.append(
                TextSection(
                    link=browse_url,
                    text="\n".join(att_lines).strip(),
                )
            )

        # Enforce max ticket size check
        total_chars = sum(len(s.text) for s in sections if s.text)
        if total_chars > JIRA_CONNECTOR_MAX_TICKET_SIZE:
            logger.warning(
                f"Skipping JSM ticket {issue_key}: size {total_chars} exceeds max {JIRA_CONNECTOR_MAX_TICKET_SIZE}"
            )
            return None

        # Structured Metadata for filtering/search
        metadata: dict[str, str | list[str]] = {
            "issue_key": issue_key,
        }
        if project_key:
            metadata["project"] = project_key
        if project_name:
            metadata["project_name"] = project_name
        if service_desk_id:
            metadata["service_desk_id"] = service_desk_id
        if service_desk and service_desk.project_name:
            metadata["service_desk_name"] = service_desk.project_name
        if queue_info:
            metadata["queue_id"] = queue_info.id
            metadata["queue_name"] = queue_info.name
        if request_type_name:
            metadata["request_type"] = request_type_name
        if issue_type_name:
            metadata["issue_type"] = issue_type_name
        if status_name:
            metadata["status"] = status_name
        if status_category:
            metadata["status_category"] = status_category
        if priority_name:
            metadata["priority"] = priority_name
        if resolution_name:
            metadata["resolution"] = resolution_name
        if reporter_info and (reporter_info.display_name or reporter_info.email):
            metadata["reporter"] = (
                reporter_info.display_name or reporter_info.email or ""
            )
        if assignee_info and (assignee_info.display_name or assignee_info.email):
            metadata["assignee"] = (
                assignee_info.display_name or assignee_info.email or ""
            )
        if labels:
            metadata["labels"] = labels
        if components:
            metadata["components"] = components
        if organizations:
            metadata["organizations"] = organizations
        if sla_metrics:
            populate_sla_metadata(sla_metrics, metadata)

        parent_node = self._build_hierarchy_node(
            service_desk=service_desk,
            project_key=project_key,
            project_name=project_name,
        )

        return Document(
            id=browse_url,
            sections=sections,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{issue_key}: {summary}",
            metadata=metadata,
            doc_updated_at=updated_dt,
            primary_owners=primary_owners or None,
            secondary_owners=secondary_owners or None,
            parent_hierarchy_raw_node_id=(
                parent_node.raw_node_id if parent_node else None
            ),
        )

    # -------------------------------------------------------------------------
    # Checkpointed Indexing, Load & Poll Interfaces
    # -------------------------------------------------------------------------

    def build_dummy_checkpoint(self) -> JiraServiceManagementCheckpoint:
        return JiraServiceManagementCheckpoint(has_more=True)

    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> JiraServiceManagementCheckpoint:
        return JiraServiceManagementCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementCheckpoint,
    ) -> Generator[
        Document | HierarchyNode | ConnectorFailure,
        None,
        JiraServiceManagementCheckpoint,
    ]:
        if not checkpoint.has_more:
            return checkpoint

        self._discover_service_desks()

        # Emit hierarchy nodes for known service desks on the first page
        is_first_page = (
            checkpoint.start_at == 0
            and checkpoint.next_page_token is None
            and checkpoint.current_service_desk_idx == 0
            and checkpoint.current_queue_idx == 0
        )
        if is_first_page:
            emitted_raw_ids: set[str] = set()
            for sd in self._service_desks_by_id.values():
                if (
                    self.service_desk_ids
                    and sd.id not in self.service_desk_ids
                ):
                    continue
                if (
                    self.project_key
                    and sd.project_key
                    and sd.project_key.upper() != self.project_key.upper()
                ):
                    continue
                node = self._build_hierarchy_node(
                    service_desk=sd,
                    project_key=sd.project_key,
                    project_name=sd.project_name,
                )
                if node and node.raw_node_id not in emitted_raw_ids:
                    emitted_raw_ids.add(node.raw_node_id)
                    yield node

        # Mode A: Explicit queue_ids configured (and no custom jql_query overriding)
        if self.queue_ids and not self.jql_query:
            return (
                yield from self._load_from_queues_checkpoint(
                    start=start,
                    end=end,
                    checkpoint=checkpoint,
                )
            )

        # Mode B: JQL search (with automatic fallback to /rest/servicedeskapi/request)
        return (
            yield from self._load_from_jql_checkpoint(
                start=start,
                end=end,
                checkpoint=checkpoint,
            )
        )

    def _load_from_queues_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementCheckpoint,
    ) -> Generator[
        Document | HierarchyNode | ConnectorFailure,
        None,
        JiraServiceManagementCheckpoint,
    ]:
        queues = self._resolve_queues_to_fetch()
        if not queues or checkpoint.current_queue_idx >= len(queues):
            checkpoint.has_more = False
            return checkpoint

        seen_keys = set(checkpoint.seen_issue_keys)
        current_q = queues[checkpoint.current_queue_idx]
        sd_id = current_q.service_desk_id or ""

        data = self.client._get_json(
            f"/rest/servicedeskapi/servicedesk/{sd_id}/queue/{current_q.id}/issue",
            params={
                "start": checkpoint.start_at,
                "limit": self.batch_size,
            },
        )
        raw_issues = data.get("values")
        if not isinstance(raw_issues, list):
            raise JiraServiceManagementClientError(
                f"Malformed queue response for queue {current_q.id}: expected 'values' list."
            )
        issues = [i for i in raw_issues if isinstance(i, dict)]
        is_last_page = data.get("isLastPage", len(issues) < self.batch_size)

        for issue in issues:
            issue_key = str(issue.get("key") or issue.get("id") or "").strip()
            if not issue_key or issue_key in seen_keys:
                continue
            seen_keys.add(issue_key)

            # Filter by time window if start/end provided
            fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
            updated_dt = parse_jsm_datetime(fields.get("updated"))
            if updated_dt is not None:
                updated_ts = updated_dt.timestamp()
                if start and updated_ts < start:
                    continue
                if end and updated_ts > end:
                    continue

            skip_reason = self._should_skip_issue(issue)
            if skip_reason:
                logger.debug(f"Skipping {issue_key}: {skip_reason}")
                continue

            try:
                doc = self._convert_issue_to_document(
                    issue=issue,
                    queue_info=current_q,
                )
                if doc is not None:
                    yield doc
            except Exception as exc:
                browse_url = build_jsm_browse_url(
                    self.jira_service_management_base_url, issue_key
                )
                yield ConnectorFailure(
                    failure_message=f"Failed to process JSM issue {issue_key}: {exc}",
                    failed_document=DocumentFailure(
                        document_id=browse_url,
                        document_link=browse_url,
                    ),
                    exception=exc,
                )

        next_checkpoint = checkpoint.model_copy(deep=True)
        next_checkpoint.seen_issue_keys = list(seen_keys)

        if is_last_page or not issues:
            next_checkpoint.current_queue_idx += 1
            next_checkpoint.start_at = 0
            next_checkpoint.has_more = next_checkpoint.current_queue_idx < len(queues)
        else:
            next_checkpoint.start_at += len(issues)
            next_checkpoint.has_more = True

        return next_checkpoint

    def _load_from_jql_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementCheckpoint,
    ) -> Generator[
        Document | HierarchyNode | ConnectorFailure,
        None,
        JiraServiceManagementCheckpoint,
    ]:
        effective_start = start if start > 0 else None
        effective_end = end if end < 4102444800 else None  # Only add upper bound when meaningful
        jql = self.build_jql_query(start=effective_start, end=effective_end)

        seen_keys = set(checkpoint.seen_issue_keys)

        try:
            issues, next_cursor, _ = self.client.search_jql_page(
                jql=jql,
                fields=["*all"],
                expand="renderedFields",
                start_at=checkpoint.start_at,
                max_results=self.batch_size,
                next_page_token=checkpoint.next_page_token,
            )
        except JiraServiceManagementClientError as exc:
            if exc.status_code == 403 and not self.jql_query:
                logger.info(
                    "JQL search returned 403; falling back to /rest/servicedeskapi/request"
                )
                return (
                    yield from self._load_from_customer_requests_checkpoint(
                        start=start,
                        end=end,
                        checkpoint=checkpoint,
                    )
                )
            raise

        for issue in issues:
            issue_key = str(issue.get("key") or issue.get("id") or "").strip()
            if not issue_key or issue_key in seen_keys:
                continue
            seen_keys.add(issue_key)

            skip_reason = self._should_skip_issue(issue)
            if skip_reason:
                logger.debug(f"Skipping {issue_key}: {skip_reason}")
                continue

            try:
                doc = self._convert_issue_to_document(issue=issue)
                if doc is not None:
                    yield doc
            except Exception as exc:
                browse_url = build_jsm_browse_url(
                    self.jira_service_management_base_url, issue_key
                )
                yield ConnectorFailure(
                    failure_message=f"Failed to process JSM issue {issue_key}: {exc}",
                    failed_document=DocumentFailure(
                        document_id=browse_url,
                        document_link=browse_url,
                    ),
                    exception=exc,
                )

        next_checkpoint = checkpoint.model_copy(deep=True)

        if next_cursor and issues:
            if next_cursor.isdigit():
                next_checkpoint.start_at = int(next_cursor)
                next_checkpoint.next_page_token = None
            else:
                next_checkpoint.next_page_token = next_cursor
            next_checkpoint.has_more = True
        else:
            next_checkpoint.has_more = False
            next_checkpoint.next_page_token = None

        return next_checkpoint

    def _load_from_customer_requests_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementCheckpoint,
    ) -> Generator[
        Document | HierarchyNode | ConnectorFailure,
        None,
        JiraServiceManagementCheckpoint,
    ]:
        target_desk_ids = self._resolve_target_service_desk_ids()
        if (self.service_desk_ids or self.project_key) and not target_desk_ids:
            raise ConnectorValidationError(
                "Could not resolve target Service Desk IDs for configured scope."
            )
        if target_desk_ids and checkpoint.current_service_desk_idx >= len(target_desk_ids):
            next_cp = checkpoint.model_copy(deep=True)
            next_cp.has_more = False
            return next_cp

        current_desk_id = (
            target_desk_ids[checkpoint.current_service_desk_idx]
            if target_desk_ids
            else None
        )
        allowed_desk_ids = set(target_desk_ids) if target_desk_ids else None

        params: dict[str, Any] = {
            "start": checkpoint.start_at,
            "limit": self.batch_size,
            "expand": "serviceDesk,requestType,participant,status,sla,comment,attachment",
        }
        if current_desk_id:
            params["serviceDeskId"] = current_desk_id

        data = self.client._get_json("/rest/servicedeskapi/request", params=params)
        raw_reqs = data.get("values")
        if not isinstance(raw_reqs, list):
            raise JiraServiceManagementClientError(
                "Malformed customer request response: expected 'values' list."
            )
        requests_list = [r for r in raw_reqs if isinstance(r, dict)]
        is_last_page = data.get("isLastPage", len(requests_list) < self.batch_size)
        seen_keys: set[str] = set()

        for req in requests_list:
            req_desk_id = (
                str(req.get("serviceDeskId")).strip()
                if req.get("serviceDeskId") is not None
                else None
            )
            if allowed_desk_ids is not None and req_desk_id not in allowed_desk_ids:
                continue

            issue_key = str(req.get("issueKey") or req.get("issueId") or "").strip()
            if not issue_key or issue_key in seen_keys:
                continue
            seen_keys.add(issue_key)

            status_date = (
                req.get("currentStatus", {}).get("statusDate")
                if isinstance(req.get("currentStatus"), dict)
                else None
            )
            updated_dt = parse_jsm_datetime(status_date or req.get("createdDate"))
            if updated_dt is not None:
                ts = updated_dt.timestamp()
                if start and ts < start:
                    continue
                if end and ts > end:
                    continue

            stub_issue: dict[str, Any] = {"key": issue_key, "fields": {}}
            if self._should_skip_issue(stub_issue):
                continue

            try:
                doc = self._convert_issue_to_document(
                    issue=stub_issue,
                    jsm_request=req,
                )
                if doc is not None:
                    yield doc
            except Exception as exc:
                browse_url = build_jsm_browse_url(
                    self.jira_service_management_base_url, issue_key
                )
                yield ConnectorFailure(
                    failure_message=f"Failed to process JSM request {issue_key}: {exc}",
                    failed_document=DocumentFailure(
                        document_id=browse_url,
                        document_link=browse_url,
                    ),
                    exception=exc,
                )

        next_checkpoint = checkpoint.model_copy(deep=True)
        if is_last_page or not requests_list:
            if target_desk_ids:
                next_checkpoint.current_service_desk_idx += 1
                next_checkpoint.start_at = 0
                next_checkpoint.has_more = (
                    next_checkpoint.current_service_desk_idx < len(target_desk_ids)
                )
            else:
                next_checkpoint.has_more = False
        else:
            next_checkpoint.start_at += len(requests_list)
            next_checkpoint.has_more = True
        return next_checkpoint

    def load_from_state(
        self,
    ) -> Generator[list[Document | HierarchyNode | ConnectorFailure], None, None]:
        checkpoint = self.build_dummy_checkpoint()
        end_ts = datetime.now(tz=timezone.utc).timestamp()
        while checkpoint.has_more:
            batch: list[Document | HierarchyNode | ConnectorFailure] = []
            gen = self.load_from_checkpoint(
                start=0.0,
                end=end_ts,
                checkpoint=checkpoint,
            )
            try:
                while True:
                    item = next(gen)
                    batch.append(item)
            except StopIteration as stop:
                checkpoint = stop.value
            if batch:
                yield batch

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Generator[list[Document | HierarchyNode | ConnectorFailure], None, None]:
        checkpoint = self.build_dummy_checkpoint()
        while checkpoint.has_more:
            batch: list[Document | HierarchyNode | ConnectorFailure] = []
            gen = self.load_from_checkpoint(
                start=start,
                end=end,
                checkpoint=checkpoint,
            )
            try:
                while True:
                    item = next(gen)
                    batch.append(item)
            except StopIteration as stop:
                checkpoint = stop.value
            if batch:
                yield batch

    # -------------------------------------------------------------------------
    # SlimConnector Interfaces (Document Pruning & Permission Sync)
    # -------------------------------------------------------------------------

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: Callable[[list[SlimDocument]], None] | None = None,
    ) -> Generator[list[SlimDocument | HierarchyNode], None, None]:
        self._discover_service_desks()

        if self.queue_ids and not self.jql_query:
            queues = self._resolve_queues_to_fetch()
            for q in queues:
                if not q.service_desk_id:
                    continue
                batch: list[SlimDocument | HierarchyNode] = []
                slim_only: list[SlimDocument] = []
                sd = self._service_desks_by_id.get(q.service_desk_id)
                parent_node = self._build_hierarchy_node(
                    service_desk=sd,
                    project_key=sd.project_key if sd else self.project_key,
                    project_name=sd.project_name if sd else None,
                )
                normalized_wanted = (
                    {rt.lower() for rt in self.request_types}
                    if self.request_types
                    else None
                )
                for issue in self.client.iter_queue_issues(
                    q.service_desk_id, q.id, limit=self.batch_size
                ):
                    if self._should_skip_issue(issue):
                        continue
                    if normalized_wanted is not None:
                        rt_name = self._resolve_issue_request_type_name(issue)
                        if not rt_name or rt_name.lower() not in normalized_wanted:
                            continue
                    issue_key = str(issue.get("key") or issue.get("id") or "").strip()
                    if not issue_key:
                        continue
                    doc_url = build_jsm_browse_url(
                        self.jira_service_management_base_url, issue_key
                    )
                    slim_doc = SlimDocument(
                        id=doc_url,
                        parent_hierarchy_raw_node_id=(
                            parent_node.raw_node_id if parent_node else None
                        ),
                    )
                    batch.append(slim_doc)
                    slim_only.append(slim_doc)
                    if len(batch) >= self.batch_size:
                        if callback and slim_only:
                            callback(slim_only)
                        yield batch
                        batch = []
                        slim_only = []
                if batch:
                    if callback and slim_only:
                        callback(slim_only)
                    yield batch
            return

        jql = self.build_jql_query(start=start, end=end)
        start_at = 0
        next_token: str | None = None
        while True:
            issues, next_cursor, _ = self.client.search_jql_page(
                jql=jql,
                fields=["project", "labels", "updated"],
                start_at=start_at,
                max_results=self.batch_size,
                next_page_token=next_token,
            )
            if not issues:
                break

            batch_docs: list[SlimDocument | HierarchyNode] = []
            slim_only_batch: list[SlimDocument] = []
            for issue in issues:
                if self._should_skip_issue(issue):
                    continue
                issue_key = str(issue.get("key") or issue.get("id") or "").strip()
                if not issue_key:
                    continue
                fields = (
                    issue.get("fields")
                    if isinstance(issue.get("fields"), dict)
                    else {}
                )
                project_obj = (
                    fields.get("project")
                    if isinstance(fields.get("project"), dict)
                    else {}
                )
                p_key = str(
                    project_obj.get("key") or self.project_key or ""
                ).strip()
                p_name = str(project_obj.get("name") or p_key or "").strip()
                sd = (
                    self._service_desks_by_project_key.get(p_key.upper())
                    if p_key
                    else None
                )
                parent_node = self._build_hierarchy_node(
                    service_desk=sd,
                    project_key=p_key,
                    project_name=p_name,
                )
                doc_url = build_jsm_browse_url(
                    self.jira_service_management_base_url, issue_key
                )
                slim_doc = SlimDocument(
                    id=doc_url,
                    parent_hierarchy_raw_node_id=(
                        parent_node.raw_node_id if parent_node else None
                    ),
                )
                batch_docs.append(slim_doc)
                slim_only_batch.append(slim_doc)

            if batch_docs:
                if callback and slim_only_batch:
                    callback(slim_only_batch)
                yield batch_docs

            if not next_cursor:
                break
            if next_cursor.isdigit():
                start_at = int(next_cursor)
                next_token = None
            else:
                next_token = next_cursor

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: Callable[[list[SlimDocument]], None] | None = None,
    ) -> Generator[list[SlimDocument | HierarchyNode], None, ConnectorStopSignal]:
        yield from self.retrieve_all_slim_docs(
            start=start,
            end=end,
            callback=callback,
        )
        return ConnectorStopSignal()
