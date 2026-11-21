import base64
import json
import time
from collections.abc import Generator
from typing import Any
import requests

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira_service_desk.models import JSMCustomerRequest, JSMServiceDesk
from onyx.utils.retry_after import parse_retry_after_seconds

_MAX_RETRY_AFTER_SLEEP_SECONDS = 60


class JiraServiceManagementClient:
    """Handles authentication and pagination against Atlassian Jira Service Management REST API."""

    def __init__(
        self,
        base_url: str,
        user_email: str,
        api_token: str,
        project_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        auth_str = f"{user_email}:{api_token}"
        self.auth_header = "Basic " + base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

    def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": self.auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "OnyxJSMConnector/1.0",
        }
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code == 429:
            retry_after = parse_retry_after_seconds(response.headers.get("Retry-After"))
            sleep_sec = retry_after if retry_after is not None and retry_after > 0 else 5
            time.sleep(min(sleep_sec, _MAX_RETRY_AFTER_SLEEP_SECONDS))
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        if response.status_code == 401:
            raise CredentialExpiredError(
                "Your Jira credentials appear to be invalid or expired (HTTP 401)."
            )
        elif response.status_code == 403:
            raise InsufficientPermissionsError(
                "Your Jira credentials do not have permission to access Jira Service Management (HTTP 403)."
            )
        elif response.status_code == 404:
            raise ConnectorValidationError(
                f"Jira Service Management endpoint not found at {url} (HTTP 404)."
            )

        response.raise_for_status()
        return response.json()

    def get_service_desks(self) -> list[JSMServiceDesk]:
        """Fetches all accessible Service Desks or filters by project_key."""
        desks: list[JSMServiceDesk] = []
        start = 0
        limit = 50
        while True:
            data = self._request("/rest/servicedeskapi/servicedesk", params={"start": start, "limit": limit})
            values = data.get("values", [])
            for item in values:
                desk = JSMServiceDesk.model_validate(item)
                if not self.project_key or desk.project_key.upper() == self.project_key.upper():
                    desks.append(desk)
            if data.get("isLastPage", True) or not values:
                break
            start += len(values)

        if self.project_key and not desks:
            raise ValueError(f"No Jira Service Desk found matching project key '{self.project_key}'")

        return desks

    def paginate_customer_requests(
        self,
        service_desk_id: str | None = None,
        start_epoch: int | None = None,
        batch_size: int = 50,
    ) -> Generator[JSMCustomerRequest, None, None]:
        """Paginates through customer requests for a service desk."""
        start = 0
        while True:
            params: dict[str, Any] = {
                "start": start,
                "limit": batch_size,
                "expand": "serviceDesk,requestType",
            }
            if service_desk_id:
                params["serviceDeskId"] = service_desk_id

            endpoint = "/rest/servicedeskapi/request"
            data = self._request(endpoint, params=params)

            values = data.get("values", [])
            if not values:
                break

            for val in values:
                created_epoch_ms = val.get("createdDate", {}).get("epochMillis")
                updated_epoch_ms = val.get("updatedDate", {}).get("epochMillis")
                status_epoch_ms = val.get("currentStatus", {}).get("statusDate", {}).get("epochMillis")
                ref_epoch = (updated_epoch_ms or status_epoch_ms or created_epoch_ms or 0) // 1000

                if start_epoch and ref_epoch < start_epoch:
                    continue

                req_fields = val.get("requestFieldValues", [])
                summary = val.get("summary") or ""
                description = ""
                for f in req_fields:
                    f_id = f.get("fieldId", "")
                    if f_id == "summary" and not summary:
                        summary = f.get("value", "")
                    elif f_id == "description":
                        val_content = f.get("value", "")
                        if isinstance(val_content, dict):
                            description = json.dumps(val_content)
                        else:
                            description = str(val_content)

                created_iso = val.get("createdDate", {}).get("iso8601", "")
                status_iso = val.get("currentStatus", {}).get("statusDate", {}).get("iso8601")
                updated_iso = (
                    val.get("updatedDate", {}).get("iso8601")
                    or status_iso
                    or created_iso
                )

                req = JSMCustomerRequest(
                    issueId=str(val.get("issueId")),
                    issueKey=str(val.get("issueKey")),
                    requestTypeId=str(val.get("requestTypeId", "")),
                    serviceDeskId=str(val.get("serviceDeskId", "")),
                    createdDate=created_iso,
                    updatedDate=updated_iso,
                    summary=summary or val.get("issueKey", "JSM Ticket"),
                    description=description,
                    status=val.get("currentStatus", {}).get("status", ""),
                    raw_fields=val,
                )
                yield req

            if data.get("isLastPage", True):
                break
            start += len(values)
