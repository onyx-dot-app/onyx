from __future__ import annotations

from typing import Any

import requests
from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_MAX_TICKET_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import _perform_jql_search
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira.utils import best_effort_basic_expert_info
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

from .utils import absolute_jsm_link
from .utils import append_with_byte_limit
from .utils import build_queue_membership_map
from .utils import coerce_optional_str
from .utils import format_approval_summaries
from .utils import format_queue_summaries
from .utils import format_request_field_values
from .utils import format_sla_summaries
from .utils import get_approval
from .utils import get_customer_request
from .utils import jsm_user_to_basic_expert_info
from .utils import JSMQueue
from .utils import JSMRequestType
from .utils import JSMServiceDesk
from .utils import list_request_approvals
from .utils import list_request_participants
from .utils import list_request_slas
from .utils import list_request_types
from .utils import list_service_desks
from .utils import stringify_jsm_value

logger = setup_logger()

_FIELD_REPORTER = "reporter"
_FIELD_PROJECT = "project"

_METADATA_SERVICE_DESK = "jsm_service_desk"
_METADATA_SERVICE_DESK_ID = "jsm_service_desk_id"
_METADATA_REQUEST_ID = "jsm_request_id"
_METADATA_REQUEST_STATUS = "jsm_request_status"
_METADATA_REQUEST_PORTAL_URL = "jsm_request_portal_url"
_METADATA_REQUEST_TYPE = "jsm_request_type"
_METADATA_REQUEST_TYPE_ID = "jsm_request_type_id"
_METADATA_REQUEST_TYPE_GROUPS = "jsm_request_type_group_ids"
_METADATA_CUSTOMER = "jsm_customer"
_METADATA_CUSTOMER_EMAIL = "jsm_customer_email"
_METADATA_CUSTOMER_ACCOUNT_ID = "jsm_customer_account_id"
_METADATA_PARTICIPANTS = "jsm_participants"
_METADATA_APPROVALS = "jsm_approvals"
_METADATA_QUEUES = "jsm_queues"
_METADATA_SLAS = "jsm_slas"


JiraServiceManagementConnectorCheckpoint = JiraConnectorCheckpoint


class JiraServiceManagementConnector(JiraConnector):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] | None = None,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=(
                JIRA_CONNECTOR_LABELS_TO_SKIP
                if labels_to_skip is None
                else labels_to_skip
            ),
            jql_query=jql_query,
            scoped_token=scoped_token,
        )
        self._service_desk_by_project_key: dict[str, JSMServiceDesk] | None = None
        self._request_types_by_service_desk_id: dict[str, dict[str, JSMRequestType]] = (
            {}
        )
        self._queue_membership_by_service_desk_id: dict[
            str, dict[str, list[JSMQueue]]
        ] = {}
        self._warning_cache: set[str] = set()

    @property
    @override
    def document_source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._service_desk_by_project_key = None
        self._request_types_by_service_desk_id.clear()
        self._queue_membership_by_service_desk_id.clear()
        self._warning_cache.clear()
        return super().load_credentials(credentials)

    @override
    def _get_document_external_access(
        self,
        project_key: str,
        add_prefix: bool,
    ) -> Any:
        del project_key
        del add_prefix
        # JSM request visibility can differ from Jira project visibility. Until
        # request-level permission sync is implemented, do not assign doc-level perms.
        return None

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        scope_jql = self._get_service_desk_scope_jql()
        time_jql = self._build_time_jql(start=start, end=end)

        if self.jql_query:
            return f"({scope_jql}) AND ({self.jql_query}) AND {time_jql}"

        return f"({scope_jql}) AND {time_jql}"

    @override
    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        try:
            service_desk_by_project_key = self._get_service_desk_by_project_key()
        except Exception as exc:
            self._handle_jira_connector_settings_error(exc)
            raise RuntimeError(
                "_handle_jira_connector_settings_error returned unexpectedly"
            )

        if not service_desk_by_project_key:
            raise ConnectorValidationError(
                "No Jira Service Management service desks were accessible with the provided credentials."
            )

        if self.jira_project and self.jira_project not in service_desk_by_project_key:
            raise ConnectorValidationError(
                f"Project '{self.jira_project}' is not an accessible Jira Service Management service desk."
            )

        if self.jql_query:
            try:
                next(
                    iter(
                        _perform_jql_search(
                            jira_client=self.jira_client,
                            jql=f"({self._get_service_desk_scope_jql()}) AND ({self.jql_query})",
                            start=0,
                            max_results=1,
                            all_issue_ids=[],
                        )
                    ),
                    None,
                )
            except Exception as exc:
                self._handle_jira_connector_settings_error(exc)
                raise RuntimeError(
                    "_handle_jira_connector_settings_error returned unexpectedly"
                )

    @override
    def _process_issue(
        self,
        issue: Issue,
        parent_hierarchy_raw_node_id: str | None,
    ) -> Document | None:
        document = super()._process_issue(
            issue=issue,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        )
        if document is None:
            return None

        service_desk = self._get_service_desk_for_issue(issue)
        if service_desk is None:
            logger.debug(
                "Skipping Jira issue %s: could not map it to a known JSM service desk",
                issue.key,
            )
            return None

        request = get_customer_request(
            jira_client=self.jira_client,
            issue_id_or_key=issue.key,
        )
        if request is None:
            logger.debug(
                "Skipping Jira issue %s because its JSM request details were unavailable",
                issue.key,
            )
            return None

        participants = self._get_request_participants(
            service_desk.service_desk_id, issue.key
        )
        slas = self._get_request_slas(service_desk.service_desk_id, issue.key)
        approvals = self._get_request_approvals(
            service_desk.service_desk_id, issue.key
        )
        request_type = self._get_request_type(service_desk.service_desk_id, request)
        queues = self._get_request_queues(service_desk.service_desk_id, issue.key)

        jsm_metadata = self._build_jsm_metadata(
            issue=issue,
            service_desk=service_desk,
            request=request,
            request_type=request_type,
            participants=participants,
            approvals=approvals,
            slas=slas,
            queues=queues,
        )
        document.metadata.update(jsm_metadata)

        jsm_text = self._build_jsm_text(
            issue=issue,
            service_desk=service_desk,
            request=request,
            request_type=request_type,
            participants=participants,
            approvals=approvals,
            slas=slas,
            queues=queues,
        )

        existing_section = document.sections[0] if document.sections else None
        if isinstance(existing_section, TextSection):
            existing_section.text = append_with_byte_limit(
                existing_text=existing_section.text,
                text_to_append=jsm_text,
                max_bytes=JIRA_CONNECTOR_MAX_TICKET_SIZE,
            )

        document.secondary_owners = self._build_secondary_owners(
            issue=issue,
            request=request,
            participants=participants,
            approvals=approvals,
        )
        document.additional_info = {
            "service_desk_id": service_desk.service_desk_id,
            "request_id": request.get("issueId"),
            "request_type_id": request.get("requestTypeId"),
            "queue_ids": [queue.queue_id for queue in queues],
        }
        return document

    def _get_service_desk_by_project_key(self) -> dict[str, JSMServiceDesk]:
        if self._service_desk_by_project_key is None:
            service_desk_by_project_key: dict[str, JSMServiceDesk] = {}
            for service_desk in list_service_desks(self.jira_client):
                if service_desk.project_key:
                    service_desk_by_project_key[service_desk.project_key] = service_desk
            self._service_desk_by_project_key = service_desk_by_project_key

        return self._service_desk_by_project_key

    def _get_service_desk_scope_jql(self) -> str:
        if self.jira_project:
            service_desk_by_project_key = self._get_service_desk_by_project_key()
            if self.jira_project not in service_desk_by_project_key:
                raise ConnectorValidationError(
                    f"Project '{self.jira_project}' is not an accessible Jira Service Management service desk."
                )
            return f'project = "{self.jira_project}"'

        project_keys = sorted(self._get_service_desk_by_project_key().keys())
        if not project_keys:
            raise ConnectorValidationError(
                "No Jira Service Management service desks were accessible with the provided credentials."
            )

        if len(project_keys) == 1:
            return f'project = "{project_keys[0]}"'

        quoted_project_keys = ", ".join(f'"{project_key}"' for project_key in project_keys)
        return f"project in ({quoted_project_keys})"

    def _get_service_desk_for_issue(self, issue: Issue) -> JSMServiceDesk | None:
        project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
        project_key = getattr(project, "key", None) if project is not None else None
        if project_key is None:
            return None

        return self._get_service_desk_by_project_key().get(project_key)

    def _get_request_type_map(
        self,
        service_desk_id: str,
    ) -> dict[str, JSMRequestType]:
        if service_desk_id not in self._request_types_by_service_desk_id:
            try:
                request_types = list_request_types(
                    jira_client=self.jira_client,
                    service_desk_id=service_desk_id,
                )
            except requests.HTTPError as exc:
                self._warn_once(
                    warning_key=f"request_types:{service_desk_id}",
                    message=(
                        "Unable to fetch Jira Service Management request types for "
                        f"service desk {service_desk_id}: {exc}"
                    ),
                )
                return {}

            self._request_types_by_service_desk_id[service_desk_id] = {
                request_type.request_type_id: request_type for request_type in request_types
            }

        return self._request_types_by_service_desk_id[service_desk_id]

    def _get_request_type(
        self,
        service_desk_id: str,
        request: dict[str, Any],
    ) -> JSMRequestType | None:
        request_type_id = request.get("requestTypeId")
        if request_type_id is not None:
            request_type = self._get_request_type_map(service_desk_id).get(
                str(request_type_id)
            )
            if request_type is not None:
                return request_type

        raw_request_type = request.get("requestType")
        if not isinstance(raw_request_type, dict):
            return None

        raw_group_ids = raw_request_type.get("groupIds", [])
        group_ids = tuple(
            str(group_id)
            for group_id in raw_group_ids
            if group_id is not None and str(group_id).strip()
        )
        derived_request_type_id = raw_request_type.get("id") or request_type_id
        if derived_request_type_id is None:
            return None

        return JSMRequestType(
            request_type_id=str(derived_request_type_id),
            name=coerce_optional_str(raw_request_type.get("name")),
            description=coerce_optional_str(raw_request_type.get("description")),
            help_text=coerce_optional_str(raw_request_type.get("helpText")),
            issue_type_id=coerce_optional_str(raw_request_type.get("issueTypeId")),
            group_ids=group_ids,
        )

    def _get_request_queues(
        self,
        service_desk_id: str,
        issue_key: str,
    ) -> list[JSMQueue]:
        if service_desk_id not in self._queue_membership_by_service_desk_id:
            try:
                self._queue_membership_by_service_desk_id[service_desk_id] = (
                    build_queue_membership_map(
                        jira_client=self.jira_client,
                        service_desk_id=service_desk_id,
                    )
                )
            except requests.HTTPError as exc:
                self._warn_once(
                    warning_key=f"queues:{service_desk_id}",
                    message=(
                        "Unable to fetch Jira Service Management queues for "
                        f"service desk {service_desk_id}: {exc}"
                    ),
                )
                return []

        return self._queue_membership_by_service_desk_id[service_desk_id].get(
            issue_key,
            [],
        )

    def _get_request_participants(
        self,
        service_desk_id: str,
        issue_key: str,
    ) -> list[dict[str, Any]]:
        try:
            return list_request_participants(
                jira_client=self.jira_client,
                issue_id_or_key=issue_key,
            )
        except requests.HTTPError as exc:
            self._warn_once(
                warning_key=f"participants:{service_desk_id}",
                message=(
                    "Unable to fetch Jira Service Management participants for "
                    f"service desk {service_desk_id} (latest issue {issue_key}): {exc}"
                ),
            )
            return []

    def _get_request_slas(
        self,
        service_desk_id: str,
        issue_key: str,
    ) -> list[dict[str, Any]]:
        try:
            return list_request_slas(
                jira_client=self.jira_client,
                issue_id_or_key=issue_key,
            )
        except requests.HTTPError as exc:
            self._warn_once(
                warning_key=f"slas:{service_desk_id}",
                message=(
                    "Unable to fetch Jira Service Management SLAs for "
                    f"service desk {service_desk_id} (latest issue {issue_key}): {exc}"
                ),
            )
            return []

    def _get_request_approvals(
        self,
        service_desk_id: str,
        issue_key: str,
    ) -> list[dict[str, Any]]:
        try:
            approvals = list_request_approvals(
                jira_client=self.jira_client,
                issue_id_or_key=issue_key,
            )
        except requests.HTTPError as exc:
            self._warn_once(
                warning_key=f"approvals:{service_desk_id}",
                message=(
                    "Unable to fetch Jira Service Management approvals for "
                    f"service desk {service_desk_id} (latest issue {issue_key}): {exc}"
                ),
            )
            return []

        detailed_approvals: list[dict[str, Any]] = []
        for approval in approvals:
            approval_id = approval.get("id")
            if approval_id is None:
                detailed_approvals.append(approval)
                continue

            if approval.get("approvers") and approval.get("finalDecision") is not None:
                detailed_approvals.append(approval)
                continue

            try:
                approval_detail = get_approval(
                    jira_client=self.jira_client,
                    issue_id_or_key=issue_key,
                    approval_id=str(approval_id),
                )
            except requests.HTTPError as exc:
                self._warn_once(
                    warning_key=f"approval-detail:{service_desk_id}",
                    message=(
                        "Unable to fetch Jira Service Management approval detail for "
                        f"service desk {service_desk_id} "
                        f"(latest issue {issue_key}/{approval_id}): {exc}"
                    ),
                )
                approval_detail = None

            detailed_approvals.append(approval_detail or approval)

        return detailed_approvals

    def _build_jsm_metadata(
        self,
        issue: Issue,
        service_desk: JSMServiceDesk,
        request: dict[str, Any],
        request_type: JSMRequestType | None,
        participants: list[dict[str, Any]],
        approvals: list[dict[str, Any]],
        slas: list[dict[str, Any]],
        queues: list[JSMQueue],
    ) -> dict[str, str | list[str]]:
        metadata: dict[str, str | list[str]] = {
            _METADATA_SERVICE_DESK_ID: service_desk.service_desk_id,
        }

        raw_service_desk = request.get("serviceDesk")
        service_desk_name = None
        if isinstance(raw_service_desk, dict):
            service_desk_name = coerce_optional_str(
                raw_service_desk.get("projectName") or raw_service_desk.get("name")
            )
        if service_desk_name is None:
            service_desk_name = service_desk.project_name
        if service_desk_name:
            metadata[_METADATA_SERVICE_DESK] = service_desk_name

        request_id = coerce_optional_str(request.get("issueId"))
        if request_id:
            metadata[_METADATA_REQUEST_ID] = request_id

        current_status = request.get("currentStatus")
        if isinstance(current_status, dict):
            current_status_str = coerce_optional_str(
                current_status.get("status") or current_status.get("statusCategory")
            )
            if current_status_str:
                metadata[_METADATA_REQUEST_STATUS] = current_status_str

        portal_url = absolute_jsm_link(
            self.jira_base,
            _extract_portal_link(request),
        )
        if portal_url:
            metadata[_METADATA_REQUEST_PORTAL_URL] = portal_url

        if request_type is not None:
            if request_type.name:
                metadata[_METADATA_REQUEST_TYPE] = request_type.name
            metadata[_METADATA_REQUEST_TYPE_ID] = request_type.request_type_id
            if request_type.group_ids:
                metadata[_METADATA_REQUEST_TYPE_GROUPS] = list(request_type.group_ids)

        requester_info = self._get_requester_info(issue, request)
        if requester_info is not None:
            if requester_info.display_name:
                metadata[_METADATA_CUSTOMER] = requester_info.display_name
            if requester_info.email:
                metadata[_METADATA_CUSTOMER_EMAIL] = requester_info.email
            if requester_info.display_name is None and requester_info.email:
                metadata[_METADATA_CUSTOMER] = requester_info.email

        requester_account_id = coerce_optional_str(
            request.get("reporter", {}).get("accountId")
            if isinstance(request.get("reporter"), dict)
            else None
        )
        if requester_account_id:
            metadata[_METADATA_CUSTOMER_ACCOUNT_ID] = requester_account_id

        participant_names = self._extract_user_display_values(participants)
        if participant_names:
            metadata[_METADATA_PARTICIPANTS] = participant_names

        approval_summaries = format_approval_summaries(approvals)
        if approval_summaries:
            metadata[_METADATA_APPROVALS] = approval_summaries

        queue_summaries = format_queue_summaries(queues)
        if queue_summaries:
            metadata[_METADATA_QUEUES] = queue_summaries

        sla_summaries = format_sla_summaries(slas)
        if sla_summaries:
            metadata[_METADATA_SLAS] = sla_summaries

        return metadata

    def _build_jsm_text(
        self,
        issue: Issue | None,
        service_desk: JSMServiceDesk,
        request: dict[str, Any],
        request_type: JSMRequestType | None,
        participants: list[dict[str, Any]],
        approvals: list[dict[str, Any]],
        slas: list[dict[str, Any]],
        queues: list[JSMQueue],
    ) -> str:
        lines = ["Jira Service Management Details:"]

        service_desk_name = service_desk.project_name or service_desk.project_key
        if service_desk_name:
            lines.append(f"Service desk: {service_desk_name}")

        if request_type is not None and request_type.name:
            lines.append(f"Request type: {request_type.name}")
        elif request.get("requestType"):
            lines.append(
                f"Request type: {stringify_jsm_value(request.get('requestType'))}"
            )

        requester_info = self._get_requester_info(issue, request)
        if requester_info is not None:
            requester_name = requester_info.get_semantic_name()
            if requester_info.email:
                lines.append(f"Customer: {requester_name} ({requester_info.email})")
            else:
                lines.append(f"Customer: {requester_name}")

        request_field_values = request.get("requestFieldValues", [])
        if isinstance(request_field_values, list):
            formatted_request_fields = format_request_field_values(
                [
                    request_field_value
                    for request_field_value in request_field_values
                    if isinstance(request_field_value, dict)
                ]
            )
            if formatted_request_fields:
                lines.append("Request fields:")
                lines.extend(formatted_request_fields)

        participant_names = self._extract_user_display_values(participants)
        if participant_names:
            lines.append(f"Participants: {', '.join(participant_names)}")

        approval_summaries = format_approval_summaries(approvals)
        if approval_summaries:
            lines.append("Approvals:")
            lines.extend(approval_summaries)

        queue_summaries = format_queue_summaries(queues)
        if queue_summaries:
            lines.append(f"Queues: {', '.join(queue_summaries)}")

        sla_summaries = format_sla_summaries(slas)
        if sla_summaries:
            lines.append("SLAs:")
            lines.extend(sla_summaries)

        portal_url = absolute_jsm_link(self.jira_base, _extract_portal_link(request))
        if portal_url:
            lines.append(f"Portal URL: {portal_url}")

        return "\n".join(lines)

    def _build_secondary_owners(
        self,
        issue: Issue,
        request: dict[str, Any],
        participants: list[dict[str, Any]],
        approvals: list[dict[str, Any]],
    ) -> list[BasicExpertInfo] | None:
        primary_owners: set[BasicExpertInfo] = set()
        reporter = best_effort_get_field_from_issue(issue, _FIELD_REPORTER)
        if reporter is not None and (
            reporter_info := best_effort_basic_expert_info(reporter)
        ):
            primary_owners.add(reporter_info)

        additional_people: set[BasicExpertInfo] = set()
        requester_info = self._get_requester_info(issue, request)
        if requester_info is not None and requester_info not in primary_owners:
            additional_people.add(requester_info)

        for participant in participants:
            participant_info = self._build_basic_expert_info_from_jsm_user(participant)
            if participant_info is not None and participant_info not in primary_owners:
                additional_people.add(participant_info)

        for approval in approvals:
            approvers = approval.get("approvers")
            if not isinstance(approvers, list):
                continue
            for approver in approvers:
                if not isinstance(approver, dict):
                    continue
                approval_user = approver.get("approver")
                if not isinstance(approval_user, dict):
                    continue
                approver_info = self._build_basic_expert_info_from_jsm_user(approval_user)
                if approver_info is not None and approver_info not in primary_owners:
                    additional_people.add(approver_info)

        if not additional_people:
            return None

        return sorted(
            additional_people,
            key=lambda info: (
                info.get_semantic_name().lower(),
                info.email or "",
            ),
        )

    def _build_basic_expert_info_from_jsm_user(
        self,
        user: dict[str, Any] | None,
    ) -> BasicExpertInfo | None:
        user_info = jsm_user_to_basic_expert_info(user)
        if user_info is None:
            return None

        return BasicExpertInfo(
            display_name=user_info.get("display_name"),
            email=user_info.get("email"),
        )

    def _get_requester_info(
        self,
        issue: Issue | None,
        request: dict[str, Any],
    ) -> BasicExpertInfo | None:
        raw_reporter = request.get("reporter")
        if isinstance(raw_reporter, dict):
            requester_info = self._build_basic_expert_info_from_jsm_user(raw_reporter)
            if requester_info is not None:
                return requester_info

        if issue is None:
            return None

        reporter = best_effort_get_field_from_issue(issue, _FIELD_REPORTER)
        if reporter is not None:
            return best_effort_basic_expert_info(reporter)

        return None

    def _extract_user_display_values(
        self,
        users: list[dict[str, Any]],
    ) -> list[str]:
        display_values: list[str] = []
        for user in users:
            user_info = self._build_basic_expert_info_from_jsm_user(user)
            if user_info is None:
                continue
            display_values.append(user_info.get_semantic_name())

        # Stable dedupe preserving order
        deduped_display_values = list(dict.fromkeys(display_values))
        return deduped_display_values

    def _warn_once(self, warning_key: str, message: str) -> None:
        if warning_key in self._warning_cache:
            return

        self._warning_cache.add(warning_key)
        logger.warning(message)


def _extract_portal_link(request: dict[str, Any]) -> str | None:
    links = request.get("_links")
    if not isinstance(links, dict):
        return None

    portal_link = links.get("web") or links.get("agent")
    return coerce_optional_str(portal_link)
