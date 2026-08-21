from collections.abc import Iterator
from datetime import datetime
from typing import Any
from typing import NoReturn

import requests
from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_REQUEST_OWNERSHIP_ALL = "ALL_REQUESTS"
_JSM_REQUESTS_PATH = "/rest/servicedeskapi/request"
_JSM_SERVICEDESK_PATH = "/rest/servicedeskapi/servicedesk"
_DEFAULT_BATCH_SIZE = 100
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 60


class JsmConnectorCheckpoint(ConnectorCheckpoint):
    offset: int = 0


class JsmConnector(
    CheckpointedConnector[JsmConnectorCheckpoint],
):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        service_desk_id: str | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        comment_batch_size: int = 50,
    ) -> None:
        self.jira_base = jira_base_url.rstrip("/")
        self.project_key = project_key
        self.service_desk_id = service_desk_id
        self.batch_size = batch_size
        self.comment_batch_size = comment_batch_size
        self._session: requests.Session | None = None

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._session

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        api_token = credentials.get("jira_api_token")
        if not isinstance(api_token, str) or not api_token:
            raise ConnectorMissingCredentialError("Jira Service Management")

        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        user_email = credentials.get("jira_user_email")
        if isinstance(user_email, str) and user_email:
            session.auth = (user_email, api_token)
        else:
            session.headers.update({"Authorization": f"Bearer {api_token}"})

        self._session = session
        return None

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(
            f"{self.jira_base}{path}",
            params=params,
            timeout=_DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            self._handle_request_error(e)
        return response.json()

    def _handle_request_error(self, error: requests.HTTPError) -> NoReturn:
        status_code = error.response.status_code if error.response is not None else None
        if status_code == 401:
            raise CredentialExpiredError(
                "Jira Service Management credentials are expired or invalid (HTTP 401)."
            ) from error
        if status_code == 403:
            raise InsufficientPermissionsError(
                "Your Jira Service Management token does not have sufficient "
                "permissions (HTTP 403)."
            ) from error
        raise ConnectorValidationError(
            f"Jira Service Management request failed: {error}"
        ) from error

    def _resolve_service_desk_id(self) -> str | None:
        if self.service_desk_id:
            return self.service_desk_id
        if not self.project_key:
            return None

        service_desk = self._get_json(
            f"{_JSM_SERVICEDESK_PATH}/projectKey:{self.project_key}"
        )
        service_desk_id = service_desk.get("id")
        if service_desk_id is None:
            raise ConnectorValidationError(
                "Could not find a Jira Service Management service desk for "
                f"project {self.project_key}."
            )
        self.service_desk_id = str(service_desk_id)
        return self.service_desk_id

    def _request_list_params(self, start: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": self.batch_size,
            "requestOwnership": _REQUEST_OWNERSHIP_ALL,
            "start": start,
        }
        service_desk_id = self._resolve_service_desk_id()
        if service_desk_id:
            params["serviceDeskId"] = service_desk_id
        return params

    def _iter_requests_page(self, start: int) -> tuple[list[dict[str, Any]], bool]:
        page = self._get_json(_JSM_REQUESTS_PATH, self._request_list_params(start))
        return page.get("values", []), bool(page.get("isLastPage", False))

    def _iter_comments(self, issue_key: str) -> Iterator[dict[str, Any]]:
        start = 0
        while True:
            page = self._get_json(
                f"{_JSM_REQUESTS_PATH}/{issue_key}/comment",
                params={"limit": self.comment_batch_size, "start": start},
            )
            comments = page.get("values", [])
            yield from comments

            if page.get("isLastPage", False) or not comments:
                break
            start += len(comments)

    def _request_url(self, request: dict[str, Any]) -> str:
        links = request.get("_links")
        if isinstance(links, dict) and isinstance(links.get("web"), str):
            return links["web"]

        issue_key = str(request["issueKey"])
        return f"{self.jira_base}/browse/{issue_key}"

    def _build_document(self, request: dict[str, Any]) -> Document:
        issue_key = str(request["issueKey"])
        request_url = self._request_url(request)
        field_lines, summary = _request_field_lines_and_summary(request)
        comments = [
            _format_comment(comment) for comment in self._iter_comments(issue_key)
        ]
        text = "\n".join(field_lines + comments)

        metadata = _request_metadata(request)
        primary_owner = _person_from_jsm_user(request.get("reporter"))

        return Document(
            id=request_url,
            sections=[TextSection(link=request_url, text=text)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{issue_key}: {summary}",
            title=f"{issue_key} {summary}",
            doc_updated_at=_request_updated_at(request),
            primary_owners=[primary_owner] if primary_owner else None,
            metadata=metadata,
        )

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: JsmConnectorCheckpoint,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        requests_page, is_last_page = self._iter_requests_page(checkpoint.offset)
        next_checkpoint = JsmConnectorCheckpoint(
            offset=checkpoint.offset + len(requests_page),
            has_more=not is_last_page and bool(requests_page),
        )

        for request in requests_page:
            issue_key = str(request.get("issueKey", ""))
            try:
                yield self._build_document(request)
            except Exception as e:
                logger.exception("Failed to process Jira Service Management request")
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=issue_key,
                        document_link=self._request_url(request) if issue_key else None,
                    ),
                    failure_message=(
                        "Failed to process Jira Service Management request: "
                        f"{str(e)}"
                    ),
                    exception=e,
                )

        return next_checkpoint

    @override
    def validate_connector_settings(self) -> None:
        if self._session is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        self._resolve_service_desk_id()
        self._get_json(
            _JSM_REQUESTS_PATH,
            params={**self._request_list_params(0), "limit": 1},
        )

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint(offset=0, has_more=True)


def _request_field_lines_and_summary(request: dict[str, Any]) -> tuple[list[str], str]:
    lines: list[str] = []
    summary = str(request.get("issueKey", "Jira Service Management request"))

    for field in request.get("requestFieldValues", []):
        if not isinstance(field, dict):
            continue

        label = str(field.get("label") or field.get("fieldId") or "Field")
        value = _coerce_jsm_text(field.get("renderedValue", field.get("value")))
        if not value:
            continue
        if label.lower() == "summary":
            summary = value
        lines.append(f"{label}: {value}")

    return lines, summary


def _request_metadata(request: dict[str, Any]) -> dict[str, str | list[str]]:
    metadata: dict[str, str | list[str]] = {"issue_key": str(request["issueKey"])}

    if service_desk_id := request.get("serviceDeskId"):
        metadata["service_desk_id"] = str(service_desk_id)
    if request_type_id := request.get("requestTypeId"):
        metadata["request_type_id"] = str(request_type_id)
    if status := _current_status(request):
        metadata["status"] = status

    if reporter := _person_from_jsm_user(request.get("reporter")):
        metadata["reporter"] = reporter.get_semantic_name()
        if reporter.email:
            metadata["reporter_email"] = reporter.email

    participant_names: list[str] = []
    participant_emails: list[str] = []
    participants = request.get("participants")
    if isinstance(participants, dict):
        for participant in participants.get("values", []):
            if person := _person_from_jsm_user(participant):
                participant_names.append(person.get_semantic_name())
                if person.email:
                    participant_emails.append(person.email)

    if participant_names:
        metadata["participants"] = participant_names
    if participant_emails:
        metadata["participant_emails"] = participant_emails

    return metadata


def _current_status(request: dict[str, Any]) -> str | None:
    status = request.get("currentStatus")
    if not isinstance(status, dict):
        return None
    raw_status = status.get("status")
    return str(raw_status) if raw_status else None


def _request_updated_at(request: dict[str, Any]) -> datetime | None:
    current_status = request.get("currentStatus")
    if isinstance(current_status, dict):
        status_date = current_status.get("statusDate")
        if parsed := _parse_jsm_datetime(status_date):
            return parsed

    return _parse_jsm_datetime(request.get("createdDate"))


def _parse_jsm_datetime(value: Any) -> datetime | None:
    if isinstance(value, dict):
        value = value.get("iso8601")
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _person_from_jsm_user(value: Any) -> BasicExpertInfo | None:
    if not isinstance(value, dict):
        return None
    display_name = value.get("displayName")
    email = value.get("emailAddress")
    if not display_name and not email:
        return None
    return BasicExpertInfo(
        display_name=str(display_name) if display_name else None,
        email=str(email) if email else None,
    )


def _format_comment(comment: dict[str, Any]) -> str:
    author = _person_from_jsm_user(comment.get("author"))
    author_text = f" by {author.get_semantic_name()}" if author else ""
    created_at = comment.get("createdDate")
    if isinstance(created_at, dict):
        created_at = created_at.get("iso8601")
    date_text = f" at {created_at}" if isinstance(created_at, str) else ""
    body = _coerce_jsm_text(comment.get("body"))
    return f"Comment{author_text}{date_text}: {body}"


def _coerce_jsm_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(filter(None, (_coerce_jsm_text(item) for item in value)))
    if isinstance(value, dict):
        adf_text = _extract_adf_text(value)
        if adf_text:
            return adf_text
        labels = []
        for key in ("name", "displayName", "label", "value"):
            if value.get(key):
                labels.append(str(value[key]))
        if labels:
            return " ".join(labels)
        return " ".join(
            filter(None, (_coerce_jsm_text(item) for item in value.values()))
        )
    return str(value)


def _extract_adf_text(value: dict[str, Any]) -> str:
    texts: list[str] = []

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            texts.append(node["text"])
        for child in node.get("content", []):
            visit(child)

    visit(value)
    return " ".join(texts)
