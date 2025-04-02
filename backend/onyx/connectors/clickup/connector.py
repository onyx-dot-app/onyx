from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rate_limit_builder,
)
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.retry_wrapper import retry_builder


CLICKUP_API_BASE_URL = "https://api.clickup.com/api/v2"


class ClickupConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        api_token: str | None = None,
        team_id: str | None = None,
        connector_type: str | None = None,
        connector_ids: list[str] | None = None,
        retrieve_task_comments: bool = True,
    ) -> None:
        self.batch_size = batch_size
        self.api_token = api_token
        self.team_id = team_id
        self.connector_type = connector_type if connector_type else "workspace"
        self.connector_ids = connector_ids
        self.retrieve_task_comments = retrieve_task_comments

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.api_token = credentials["clickup_api_token"]
        self.team_id = credentials["clickup_team_id"]
        return None

    @retry_builder()
    @rate_limit_builder(max_calls=100, period=60)
    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Any:
        if not self.api_token:
            raise ConnectorMissingCredentialError("Clickup")

        headers = {"Authorization": self.api_token}

        response = requests.get(
            f"{CLICKUP_API_BASE_URL}/{endpoint}", headers=headers, params=params
        )

        response.raise_for_status()

        return response.json()

    def _get_task_comments(self, task_id: str) -> list[TextSection]:
        url_endpoint = f"/task/{task_id}/comment"
        response = self._make_request(url_endpoint)
        comments = [
            TextSection(
                link=f'https://app.clickup.com/t/{task_id}?comment={comment_dict["id"]}',
                text=comment_dict["comment_text"],
            )
            for comment_dict in response["comments"]
        ]

        return comments

    def _get_all_tasks_filtered(
        self,
        start: int | None = None,
        end: int | None = None,
    ) -> GenerateDocumentsOutput:
        doc_batch: list[Document] = []
        page: int = 0
        params = {
            "include_markdown_description": "true",
            "include_closed": "true",
            "page": page,
        }

        if start is not None:
            params["date_updated_gt"] = start
        if end is not None:
            params["date_updated_lt"] = end

        if self.connector_type == "list":
            params["list_ids[]"] = self.connector_ids
        elif self.connector_type == "folder":
            params["project_ids[]"] = self.connector_ids
        elif self.connector_type == "space":
            params["space_ids[]"] = self.connector_ids

        url_endpoint = f"/team/{self.team_id}/task"

        while True:
            response = self._make_request(url_endpoint, params)

            page += 1
            params["page"] = page

            for task in response["tasks"]:
                document = Document(
                    id=task["id"],
                    source=DocumentSource.CLICKUP,
                    semantic_identifier=task["name"],
                    doc_updated_at=(
                        datetime.fromtimestamp(
                            round(float(task["date_updated"]) / 1000, 3)
                        ).replace(tzinfo=timezone.utc)
                    ),
                    primary_owners=[
                        BasicExpertInfo(
                            display_name=task["creator"]["username"],
                            email=task["creator"]["email"],
                        )
                    ],
                    secondary_owners=[
                        BasicExpertInfo(
                            display_name=assignee["username"],
                            email=assignee["email"],
                        )
                        for assignee in task["assignees"]
                    ],
                    title=task["name"],
                    sections=[
                        TextSection(
                            link=task["url"],
                            text=(
                                task["markdown_description"]
                                if "markdown_description" in task
                                else task["description"]
                            ),
                        )
                    ],
                    metadata={
                        "id": task["id"],
                        "status": task["status"]["status"],
                        "list": task["list"]["name"],
                        "project": task["project"]["name"],
                        "folder": task["folder"]["name"],
                        "space_id": task["space"]["id"],
                        "tags": [tag["name"] for tag in task["tags"]],
                        "priority": (
                            task["priority"]["priority"]
                            if "priority" in task and task["priority"] is not None
                            else ""
                        ),
                    },
                )

                extra_fields = [
                    "date_created",
                    "date_updated",
                    "date_closed",
                    "date_done",
                    "due_date",
                ]
                for extra_field in extra_fields:
                    if extra_field in task and task[extra_field] is not None:
                        document.metadata[extra_field] = task[extra_field]

                if self.retrieve_task_comments:
                    document.sections.extend(self._get_task_comments(task["id"]))

                doc_batch.append(document)

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

            if response.get("last_page") is True or len(response["tasks"]) < 100:
                break

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        if self.api_token is None:
            raise ConnectorMissingCredentialError("Clickup")

        return self._get_all_tasks_filtered(None, None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.api_token is None:
            raise ConnectorMissingCredentialError("Clickup")

        return self._get_all_tasks_filtered(int(start * 1000), int(end * 1000))


if __name__ == "__main__":
    import os

    clickup_connector = ClickupConnector()

    clickup_connector.load_credentials(
        {
            "clickup_api_token": os.environ["clickup_api_token"],
            "clickup_team_id": os.environ["clickup_team_id"],
        }
    )

    latest_docs = clickup_connector.load_from_state()

    for doc in latest_docs:
        print(doc)
