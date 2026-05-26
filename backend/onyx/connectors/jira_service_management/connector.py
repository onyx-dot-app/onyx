import json
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_ID_PREFIX = "JSM_"
_JSM_PER_PAGE = 50
_JSM_MAX_RETRIES = 3

_FIELD_REQUEST_FIELD_VALUES = "requestFieldValues"
_FIELD_CURRENT_STATUS = "currentStatus"
_FIELD_REQUEST_TYPE = "requestType"
_FIELD_CREATED_DATE = "createdDate"
_FIELD_ISSUE_KEY = "issueKey"
_FIELD_ISSUE_ID = "issueId"
_FIELD_DESCRIPTION = "description"
_FIELD_SUMMARY = "summary"
_FIELD_STATUS = "status"
_FIELD_STATUS_DATE = "statusDate"
_FIELD_STATUS_CATEGORY = "statusCategory"
_FIELD_PARTICIPANTS = "participants"
_FIELD_ORGANIZATION = "organization"
_FIELD_TIME_TO_RESOLUTION = "timeToResolution"
_FIELD_CUSTOMER_WAIT_TIME = "customerWaitTime"
_FIELD_LABEL = "label"
_FIELD_VALUE = "value"

_REQUEST_METADATA_FIELDS = {
    _FIELD_STATUS,
    _FIELD_TIME_TO_RESOLUTION,
    _FIELD_CUSTOMER_WAIT_TIME,
    _FIELD_ORGANIZATION,
}


@retry(tries=_JSM_MAX_RETRIES, delay=1, backoff=2)
def _rate_limited_jsm_get(
    url: str, auth: tuple, params: dict | None = None
) -> requests.Response:
    return rl_requests.get(url, auth=auth, params=params)


def _parse_jsm_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _extract_field_value(
    request: dict, field_label: str
) -> str:
    field_values = request.get(_FIELD_REQUEST_FIELD_VALUES, [])
    for field in field_values:
        if isinstance(field, dict) and field.get(_FIELD_LABEL, "").lower() == field_label.lower():
            value = field.get(_FIELD_VALUE, "")
            return str(value) if value else ""
    return ""


def _create_metadata_from_request(request: dict) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    
    for key, value in request.items():
        if key in _REQUEST_METADATA_FIELDS and value:
            if isinstance(value, dict):
                name = value.get("name") or value.get("value")
                if name:
                    metadata[key] = str(name)
            elif isinstance(value, list):
                items = []
                for item in value:
                    if isinstance(item, dict):
                        items.append(str(item.get("name", item.get("value", str(item)))))
                    else:
                        items.append(str(item))
                metadata[key] = items
            else:
                metadata[key] = str(value)
    
    current_status = request.get(_FIELD_CURRENT_STATUS, {})
    if isinstance(current_status, dict):
        status = current_status.get(_FIELD_STATUS)
        if status:
            metadata[_FIELD_STATUS] = str(status)
        category = current_status.get(_FIELD_STATUS_CATEGORY)
        if category:
            metadata[_FIELD_STATUS_CATEGORY] = str(category)
    
    request_type = request.get(_FIELD_REQUEST_TYPE, {})
    if isinstance(request_type, dict):
        type_name = request_type.get("name") or request_type.get("value")
        if type_name:
            metadata["request_type"] = str(type_name)
    
    priority_field = _extract_field_value(request, "priority")
    if priority_field:
        metadata[_FIELD_STATUS] = metadata.get(_FIELD_STATUS, "") + f" (Priority: {priority_field})"
    
    return metadata


def _create_doc_from_request(request: dict, jira_base: str) -> Document:
    issue_key = request.get(_FIELD_ISSUE_KEY, request.get(_FIELD_ISSUE_ID, ""))
    
    summary = _extract_field_value(request, _FIELD_SUMMARY)
    if not summary and request.get(_FIELD_REQUEST_FIELD_VALUES):
        for field in request[_FIELD_REQUEST_FIELD_VALUES]:
            if isinstance(field, dict) and field.get(_FIELD_LABEL, "").lower() == _FIELD_SUMMARY:
                summary = str(field.get(_FIELD_VALUE, ""))
                break
    if not summary:
        summary = issue_key
    
    description_text = _extract_field_value(request, _FIELD_DESCRIPTION)
    text_parts = []
    text_parts.append(f"Request description: {parse_html_page_basic(description_text)}")
    
    additional_fields = []
    for field in request.get(_FIELD_REQUEST_FIELD_VALUES, []):
        if isinstance(field, dict):
            label = field.get(_FIELD_LABEL, "")
            value = field.get(_FIELD_VALUE, "")
            if label and value and label.lower() not in (_FIELD_SUMMARY, _FIELD_DESCRIPTION):
                additional_fields.append(f"{label}: {value}")
    
    if additional_fields:
        text_parts.append("\n".join(additional_fields))
    
    project_key = issue_key.split("-")[0] if "-" in issue_key else ""
    link = f"{jira_base}/browse/{issue_key}"
    
    metadata = _create_metadata_from_request(request)
    
    doc_updated = _parse_jsm_timestamp(
        request.get(_FIELD_CURRENT_STATUS, {}).get(_FIELD_STATUS_DATE)
    ) or _parse_jsm_timestamp(request.get(_FIELD_CREATED_DATE))
    
    return Document(
        id=_JSM_ID_PREFIX + issue_key,
        sections=[
            TextSection(
                link=link,
                text="\n\n".join(text_parts),
            )
        ],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue_key}: {summary}" if issue_key != summary else issue_key,
        metadata=metadata,
        doc_updated_at=doc_updated,
    )


class JiraServiceManagementConnector(PollConnector, LoadConnector):
    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self.jira_base: str = ""
        self.auth: tuple[str, str] = ("", "")
        self.project_keys: list[str] = []

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        jira_base = credentials.get("jira_base_url", "")
        email = credentials.get("jira_user_email", "")
        api_token = credentials.get("jira_api_token", "")
        project_keys_raw = credentials.get("project_keys", credentials.get("jsm_project_keys", ""))
        
        if not jira_base or not api_token:
            raise ConnectorMissingCredentialError("Jira base URL and API token are required")
        
        jira_base = str(jira_base).strip().rstrip("/")
        self.jira_base = jira_base
        email_str = str(email) if email else ""
        self.auth = (email_str, str(api_token))
        
        if project_keys_raw:
            self.project_keys = [
                k.strip() for k in str(project_keys_raw).split(",") if k.strip()
            ]

    def _fetch_requests(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> Iterator[list[dict]]:
        base_url = f"{self.jira_base}/rest/servicedeskapi/request"
        params: dict[str, Any] = {
            "start": 0,
            "limit": _JSM_PER_PAGE,
        }
        
        if start:
            params["searchOn"] = "createdDate"
            params["createdDateFrom"] = start.isoformat()
        if end:
            params["createdDateTo"] = end.isoformat()
        
        total_fetched = 0
        
        while True:
            logger.info(
                "Fetching JSM requests (start=%s, limit=%s)",
                params["start"],
                params["limit"],
            )
            
            response = _rate_limited_jsm_get(base_url, auth=self.auth, params=params)
            
            if response.status_code == 404:
                logger.warning(
                    "JSM API not available at %s. "
                    "Ensure this is a Jira Service Management project.",
                    base_url,
                )
                return
            
            if response.status_code == 403:
                logger.warning(
                    "Access forbidden to JSM API. "
                    "Ensure the user has JSM agent or admin permissions."
                )
                return
            
            response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error("Failed to decode JSM response")
                return
            
            requests_list = data.get("values", [])
            if not requests_list:
                break
            
            if self.project_keys:
                filtered = []
                for r in requests_list:
                    key = r.get(_FIELD_ISSUE_KEY, "")
                    r_project = key.split("-")[0] if "-" in key else ""
                    if r_project in self.project_keys:
                        filtered.append(r)
                requests_list = filtered
            
            if not requests_list:
                break
            
            yield requests_list
            total_fetched += len(requests_list)
            
            if data.get("isLastPage", True):
                break
            
            params["start"] = params["start"] + len(requests_list)

    def _process_requests(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        doc_batch: list[Document] = []
        
        for request_batch in self._fetch_requests(start, end):
            for request in request_batch:
                doc_batch.append(_create_doc_from_request(request, self.jira_base))
                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []
        
        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_requests()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = (
            datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        )
        end_datetime = (
            datetime.fromtimestamp(end, tz=timezone.utc) if end else None
        )
        yield from self._process_requests(start_datetime, end_datetime)