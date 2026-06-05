import copy
from collections.abc import Generator, Iterable, Iterator
from datetime import datetime, timezone
from typing import Any

from onyx.configs.app_configs import JIRA_CONNECTOR_MAX_TICKET_SIZE, JIRA_SLIM_PAGE_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointOutput, GenerateSlimDocumentOutput, SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector, JiraConnectorCheckpoint
from onyx.connectors.jira.utils import build_jira_url, extract_text_from_adf
from onyx.connectors.models import BasicExpertInfo, ConnectorFailure, Document, DocumentFailure, HierarchyNode, SlimDocument
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(JiraConnector):
    def _get_service_desk_id_by_key(self, project_key: str) -> str | None:
        if not self._jira_client:
            return None
        url = self.jira_client._get_url(f"servicedesk/{project_key}")
        try:
            resp = self.jira_client._session.get(url)
            resp.raise_for_status()
            return str(resp.json().get("id"))
        except Exception as e:
            logger.error("Failed to retrieve service desk ID for project %s: %s", project_key, e)
            return None

    def _fetch_jsm_requests_page(self, start: int, limit: int, service_desk_id: str | None) -> dict[str, Any]:
        url = self.jira_client._get_url("request")
        params: dict[str, Any] = {
            "start": start,
            "limit": limit,
        }
        if service_desk_id:
            params["serviceDeskId"] = service_desk_id

        resp = self.jira_client._session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _fetch_jsm_comments(self, issue_key: str) -> list[dict[str, Any]]:
        url = self.jira_client._get_url(f"request/{issue_key}/comment")
        comments = []
        start = 0
        limit = 50
        while True:
            params = {
                "start": start,
                "limit": limit,
            }
            resp = self.jira_client._session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            values = data.get("values", [])
            comments.extend(values)
            if data.get("isLastPage", True) or not values:
                break
            start += len(values)
        return comments

    def _fetch_jsm_comments_safe(self, issue_key: str) -> list[dict[str, Any]]:
        try:
            return self._fetch_jsm_comments(issue_key)
        except Exception as e:
            logger.error("Failed to fetch comments for JSM request %s: %s", issue_key, e)
            return []

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        try:
            return self._load_from_checkpoint_jsm(
                start, end, checkpoint, include_permissions=False
            )
        except Exception as e:
            logger.error("Failed to load JSM documents from checkpoint: %s", e)
            raise e

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        try:
            return self._load_from_checkpoint_jsm(
                start, end, checkpoint, include_permissions=True
            )
        except Exception as e:
            logger.error("Failed to load JSM documents from checkpoint with perm sync: %s", e)
            raise e

    def _load_from_checkpoint_jsm(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        new_checkpoint = copy.deepcopy(checkpoint)
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset
        limit = 50

        service_desk_id = None
        if self.jira_project:
            service_desk_id = self._get_service_desk_id_by_key(self.jira_project)
            if not service_desk_id:
                logger.error("Could not resolve service desk ID for project key: %s", self.jira_project)
                new_checkpoint.has_more = False
                return new_checkpoint

        seen_hierarchy_node_ids = set(new_checkpoint.seen_hierarchy_node_ids)
        has_more_requests = True

        while has_more_requests:
            try:
                data = self._fetch_jsm_requests_page(current_offset, limit, service_desk_id)
            except Exception as e:
                logger.error("Failed to fetch JSM requests page at offset %s: %s", current_offset, e)
                raise e

            requests_list = data.get("values", [])
            if not requests_list:
                new_checkpoint.has_more = False
                break

            for request in requests_list:
                issue_key = request.get("issueKey")
                if not issue_key:
                    current_offset += 1
                    continue

                try:
                    comments = self._fetch_jsm_comments_safe(issue_key)

                    created_date_str = request.get("createdDate", {}).get("iso8601")
                    created_dt = time_str_to_utc(created_date_str) if created_date_str else datetime.fromtimestamp(0, tz=timezone.utc)

                    status_date_str = request.get("currentStatus", {}).get("statusDate", {}).get("iso8601")
                    status_dt = time_str_to_utc(status_date_str) if status_date_str else created_dt

                    comment_dts = []
                    for c in comments:
                        c_date_str = c.get("created", {}).get("iso8601")
                        if c_date_str:
                            comment_dts.append(time_str_to_utc(c_date_str))

                    latest_activity_dt = max([created_dt, status_dt] + comment_dts)
                    latest_activity_ts = latest_activity_dt.timestamp()

                    if latest_activity_ts < start:
                        has_more_requests = False
                        new_checkpoint.has_more = False
                        break

                    if latest_activity_ts > end:
                        current_offset += 1
                        continue

                    project_key = issue_key.split("-")[0]

                    yield from self._yield_project_hierarchy_node(
                        project_key, None, seen_hierarchy_node_ids
                    )

                    summary = ""
                    description = ""
                    for field in request.get("requestFieldValues", []):
                        field_id = field.get("fieldId")
                        val = field.get("value")
                        if field_id == "summary":
                            summary = str(val) if val else ""
                        elif field_id == "description":
                            if isinstance(val, dict):
                                description = extract_text_from_adf(val)
                            else:
                                description = str(val) if val else ""

                    ticket_content = f"{description}\n"
                    comment_strs = []
                    for comment in comments:
                        author_email = comment.get("author", {}).get("emailAddress", "")
                        if author_email in self.comment_email_blacklist:
                            continue
                        body_text = comment.get("body", "")
                        if isinstance(body_text, dict):
                            body_text = extract_text_from_adf(body_text)
                        else:
                            body_text = str(body_text)
                        if body_text:
                            comment_strs.append(body_text)

                    if comment_strs:
                        ticket_content += "\n".join([f"Comment: {c}" for c in comment_strs])

                    if len(ticket_content.encode("utf-8")) > JIRA_CONNECTOR_MAX_TICKET_SIZE:
                        logger.info(
                            "Skipping %s because it exceeds the maximum size of %s bytes.",
                            issue_key,
                            JIRA_CONNECTOR_MAX_TICKET_SIZE,
                        )
                        current_offset += 1
                        continue

                    page_url = request.get("_links", {}).get("web")
                    if not page_url:
                        page_url = build_jira_url(self.jira_base, issue_key)

                    people = set()
                    reporter = request.get("reporter", {})
                    reporter_name = reporter.get("displayName")
                    reporter_email = reporter.get("emailAddress")
                    if reporter_name or reporter_email:
                        people.add(BasicExpertInfo(display_name=reporter_name, email=reporter_email))

                    metadata_dict = {
                        "key": issue_key,
                        "created": created_date_str or "",
                        "status": request.get("currentStatus", {}).get("status", ""),
                        "project": project_key,
                    }

                    doc = Document(
                        id=page_url,
                        sections=[TextSection(link=page_url, text=ticket_content)],
                        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
                        semantic_identifier=f"{issue_key}: {summary}",
                        title=f"{issue_key} {summary}",
                        doc_updated_at=latest_activity_dt,
                        primary_owners=list(people) or None,
                        metadata=metadata_dict,
                        parent_hierarchy_raw_node_id=project_key,
                    )

                    if include_permissions:
                        doc.external_access = self._get_project_permissions(
                            project_key,
                            add_prefix=True,
                        )
                    yield doc

                except Exception as e:
                    logger.error("Failed to process JSM request %s: %s", issue_key, e)
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=issue_key,
                            document_link=build_jira_url(self.jira_base, issue_key),
                        ),
                        failure_message=f"Failed to process JSM request: {str(e)}",
                        exception=e,
                    )

                current_offset += 1

            if data.get("isLastPage", True):
                new_checkpoint.has_more = False
                break

        new_checkpoint.offset = current_offset
        new_checkpoint.seen_hierarchy_node_ids = list(seen_hierarchy_node_ids)
        return new_checkpoint

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: Any = None,
    ) -> GenerateSlimDocumentOutput:
        start = start or 0
        end = end or datetime.now(timezone.utc).timestamp()

        current_offset = 0
        limit = 50
        service_desk_id = None
        if self.jira_project:
            service_desk_id = self._get_service_desk_id_by_key(self.jira_project)
            if not service_desk_id:
                logger.error("Could not resolve service desk ID for project key: %s", self.jira_project)
                return

        seen_hierarchy_node_ids: set[str] = set()
        slim_doc_batch: list[SlimDocument | HierarchyNode] = []
        has_more_requests = True

        while has_more_requests:
            try:
                data = self._fetch_jsm_requests_page(current_offset, limit, service_desk_id)
            except Exception as e:
                logger.error("Failed to fetch JSM requests page for slim sync at offset %s: %s", current_offset, e)
                raise e

            requests_list = data.get("values", [])
            if not requests_list:
                break

            for request in requests_list:
                issue_key = request.get("issueKey")
                if not issue_key:
                    current_offset += 1
                    continue

                try:
                    comments = self._fetch_jsm_comments_safe(issue_key)
                    created_date_str = request.get("createdDate", {}).get("iso8601")
                    created_dt = time_str_to_utc(created_date_str) if created_date_str else datetime.fromtimestamp(0, tz=timezone.utc)
                    status_date_str = request.get("currentStatus", {}).get("statusDate", {}).get("iso8601")
                    status_dt = time_str_to_utc(status_date_str) if status_date_str else created_dt

                    comment_dts = []
                    for c in comments:
                        c_date_str = c.get("created", {}).get("iso8601")
                        if c_date_str:
                            comment_dts.append(time_str_to_utc(c_date_str))

                    latest_activity_dt = max([created_dt, status_dt] + comment_dts)
                    latest_activity_ts = latest_activity_dt.timestamp()

                    if latest_activity_ts < start:
                        has_more_requests = False
                        break

                    if latest_activity_ts > end:
                        current_offset += 1
                        continue

                    project_key = issue_key.split("-")[0]

                    for node in self._yield_project_hierarchy_node(
                        project_key, None, seen_hierarchy_node_ids
                    ):
                        slim_doc_batch.append(node)

                    page_url = request.get("_links", {}).get("web")
                    if not page_url:
                        page_url = build_jira_url(self.jira_base, issue_key)

                    slim_doc_batch.append(
                        SlimDocument(
                            id=page_url,
                            external_access=self._get_project_permissions(
                                project_key, add_prefix=False
                            ),
                            parent_hierarchy_raw_node_id=project_key,
                        )
                    )

                    if len(slim_doc_batch) >= JIRA_SLIM_PAGE_SIZE:
                        yield slim_doc_batch
                        slim_doc_batch = []

                except Exception as e:
                    logger.error("Failed to process JSM request for slim sync %s: %s", issue_key, e)

                current_offset += 1

            if data.get("isLastPage", True):
                break

        if slim_doc_batch:
            yield slim_doc_batch

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira")

        if self.jira_project:
            service_desk_id = self._get_service_desk_id_by_key(self.jira_project)
            if not service_desk_id:
                raise ConnectorValidationError(
                    f"Could not resolve Jira Service Management project key '{self.jira_project}' to a service desk."
                )
        else:
            try:
                url = self.jira_client._get_url("servicedesk")
                resp = self.jira_client._session.get(url)
                resp.raise_for_status()
            except Exception as e:
                self._handle_jira_connector_settings_error(e)
