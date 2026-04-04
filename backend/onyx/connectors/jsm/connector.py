import json
from collections.abc import Generator, Iterator
from datetime import datetime
from typing import Any

import requests
from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import IndexingHeartbeatInterface
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.connectors.jsm.utils import build_jsm_url, get_jsm_api_url, extract_text_from_adf, best_effort_basic_expert_info
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JsmConnectorCheckpoint(ConnectorCheckpoint):
    offset: int = 0

class JsmConnector(
    CheckpointedConnectorWithPermSync[JsmConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    def __init__(
        self,
        jira_base_url: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.jira_base_url = jira_base_url.rstrip("/")
        self.batch_size = batch_size
        self._api_token: str | None = None
        self._user_email: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._api_token = credentials.get("jira_api_token")
        self._user_email = credentials.get("jira_user_email")
        return None

    def _get_auth(self) -> tuple[str, str] | None:
        if self._user_email and self._api_token:
            return (self._user_email, self._api_token)
        return None

    def _fetch_requests(self, offset: int, limit: int) -> dict[str, Any]:
        url = get_jsm_api_url(self.jira_base_url, "request")
        params = {
            "start": offset,
            "limit": limit,
        }
        auth = self._get_auth()
        response = requests.get(url, params=params, auth=auth)
        response.raise_for_status()
        return response.json()

    def _fetch_comments(self, issue_key: str) -> list[str]:
        all_comments = []
        start = 0
        limit = 50
        auth = self._get_auth()
        
        while True:
            url = get_jsm_api_url(self.jira_base_url, f"request/{issue_key}/comment")
            params = {"start": start, "limit": limit}
            try:
                response = requests.get(url, params=params, auth=auth)
                response.raise_for_status()
                data = response.json()
                
                for comment in data.get("values", []):
                    body = comment.get("body")
                    if body:
                        all_comments.append(extract_text_from_adf(body))
                
                if data.get("isLastPage", True):
                    break
                start += limit
            except Exception as e:
                logger.error(f"Failed to fetch comments for {issue_key}: {e}")
                break
        return all_comments

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        offset = checkpoint.offset
        
        while True:
            data = self._fetch_requests(offset, self.batch_size)
            requests_list = data.get("values", [])
            
            for req in requests_list:
                doc = self._process_request(req)
                if doc:
                    yield doc
            
            offset += len(requests_list)
            if data.get("isLastPage", True):
                break
                
        return JsmConnectorCheckpoint(offset=offset, has_more=False)

    def build_dummy_checkpoint(self) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint(offset=0, has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> Iterator[list[SlimDocument | HierarchyNode]]:
        # JSM doesn't yet support granular permission syncing in this connector
        return
        yield []

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        # For now, we reuse the same logic as load_from_checkpoint
        return (yield from self.load_from_checkpoint(start, end, checkpoint))

    def _process_request(self, req: dict[str, Any]) -> Document | None:
        issue_key = req.get("issueKey")
        if not issue_key:
            return None

        summary = ""
        description = ""
        
        for field in req.get("requestFieldValues", []):
            label = field.get("label")
            value = field.get("value")
            if label == "Summary":
                summary = extract_text_from_adf(value)
            elif label == "Description":
                description = extract_text_from_adf(value)

        comments = self._fetch_comments(issue_key)
        comments_str = "\n\n".join([f"Comment: {c}" for c in comments])

        content = f"Summary: {summary}\n\nDescription: {description}"
        if comments_str:
            content += f"\n\n{comments_str}"
        
        service_desk_id = str(req.get("serviceDeskId", ""))
        page_url = build_jsm_url(self.jira_base_url, service_desk_id, issue_key)

        reporter = best_effort_basic_expert_info(req.get("reporter"))
        participants = [
            best_effort_basic_expert_info(p)
            for p in req.get("requestParticipants", [])
            if p
        ]
        participants = [p for p in participants if p]

        metadata = {
            "issue_key": issue_key,
            "service_desk_id": str(req.get("serviceDeskId", "")),
            "request_type_id": str(req.get("requestTypeId", "")),
            "status": req.get("currentStatus", {}).get("status", ""),
        }
        if reporter:
            display_name = reporter.get("display_name")
            email = reporter.get("email")
            if display_name and email:
                metadata["reporter"] = f"{display_name} ({email})"
            elif display_name:
                metadata["reporter"] = display_name
            elif email:
                metadata["reporter"] = email

        if participants:
            metadata["participants"] = []
            for p in participants:
                display_name = p.get("display_name")
                email = p.get("email")
                if display_name and email:
                    metadata["participants"].append(f"{display_name} ({email})")
                elif display_name:
                    metadata["participants"].append(display_name)
                elif email:
                    metadata["participants"].append(email)

        return Document(
            id=page_url,
            sections=[TextSection(link=page_url, text=content)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{issue_key}: {summary}",
            title=f"{issue_key} {summary}",
            metadata=metadata,
        )
