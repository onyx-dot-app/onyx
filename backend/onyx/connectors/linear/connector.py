import os
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import LINEAR_CLIENT_ID
from onyx.configs.app_configs import LINEAR_CLIENT_SECRET
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
)
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import OAuthConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries


logger = setup_logger()

_NUM_RETRIES = 5
_TIMEOUT = 60
_LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"


def _make_query(request_body: dict[str, Any], api_key: str) -> requests.Response:
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }

    for i in range(_NUM_RETRIES):
        try:
            response = requests.post(
                _LINEAR_GRAPHQL_URL,
                headers=headers,
                json=request_body,
                timeout=_TIMEOUT,
            )
            if not response.ok:
                raise RuntimeError(
                    f"Error fetching issues from Linear: {response.text}"
                )

            return response
        except Exception as e:
            if i == _NUM_RETRIES - 1:
                raise e

            logger.warning(f"A Linear GraphQL error occurred: {e}. Retrying...")

    raise RuntimeError(
        "Unexpected execution when querying Linear. This should never happen."
    )


class LinearConnector(LoadConnector, PollConnector, OAuthConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.batch_size = batch_size
        self.linear_api_key: str | None = None

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.LINEAR

    @classmethod
    def oauth_authorization_url(
        cls, base_domain: str, state: str, additional_kwargs: dict[str, str]
    ) -> str:
        if not LINEAR_CLIENT_ID:
            raise ValueError("LINEAR_CLIENT_ID environment variable must be set")

        callback_uri = get_oauth_callback_uri(base_domain, DocumentSource.LINEAR.value)
        return (
            f"https://linear.app/oauth/authorize"
            f"?client_id={LINEAR_CLIENT_ID}"
            f"&redirect_uri={callback_uri}"
            f"&response_type=code"
            f"&scope=read"
            f"&state={state}"
            f"&prompt=consent"  # prompts user for access; allows choosing workspace
        )

    @classmethod
    def oauth_code_to_token(
        cls, base_domain: str, code: str, additional_kwargs: dict[str, str]
    ) -> dict[str, Any]:
        data = {
            "code": code,
            "redirect_uri": get_oauth_callback_uri(
                base_domain, DocumentSource.LINEAR.value
            ),
            "client_id": LINEAR_CLIENT_ID,
            "client_secret": LINEAR_CLIENT_SECRET,
            "grant_type": "authorization_code",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = request_with_retries(
            method="POST",
            url="https://api.linear.app/oauth/token",
            data=data,
            headers=headers,
            backoff=0,
            delay=0.1,
        )
        if not response.ok:
            raise RuntimeError(f"Failed to exchange code for token: {response.text}")

        token_data = response.json()

        return {
            "access_token": token_data["access_token"],
        }

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if "linear_api_key" in credentials:
            self.linear_api_key = cast(str, credentials["linear_api_key"])
        elif "access_token" in credentials:
            self.linear_api_key = "Bearer " + cast(str, credentials["access_token"])
        else:
            # May need to handle case in the future if the OAuth flow expires
            raise ConnectorMissingCredentialError("Linear")

        return None

    def _process_issues(
        self, start_str: datetime | None = None, end_str: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.linear_api_key is None:
            raise ConnectorMissingCredentialError("Linear")

        lte_filter = f'lte: "{end_str}"' if end_str else ""
        gte_filter = f'gte: "{start_str}"' if start_str else ""
        updatedAtFilter = f"""
            {lte_filter}
            {gte_filter}
        """

        query = (
            """
            query IterateIssueBatches($first: Int, $after: String) {
                issues(
                    orderBy: updatedAt,
                    first: $first,
                    after: $after,
                    filter: {
                        updatedAt: {
        """
            + updatedAtFilter
            + """
                        },

                    }
                ) {
                    edges {
                        node {
                            id
                            createdAt
                            updatedAt
                            archivedAt
                            number
                            title
                            priority
                            estimate
                            sortOrder
                            startedAt
                            completedAt
                            startedTriageAt
                            triagedAt
                            canceledAt
                            autoClosedAt
                            autoArchivedAt
                            dueDate
                            slaStartedAt
                            slaBreachesAt
                            trashed
                            snoozedUntilAt
                            team {
                                name
                            }
                            creator {
                                name
                                email
                            }
                            assignee {
                                name
                                email
                            }
                            previousIdentifiers
                            subIssueSortOrder
                            priorityLabel
                            identifier
                            url
                            branchName
                            state {
                                id
                                name
                            }
                            customerTicketCount
                            description
                            comments {
                                nodes {
                                    url
                                    body
                                }
                            }
                        }
                    }
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                }
            }
        """
        )

        has_more = True
        endCursor = None
        while has_more:
            graphql_query = {
                "query": query,
                "variables": {
                    "first": self.batch_size,
                    "after": endCursor,
                },
            }
            logger.debug(f"Requesting issues from Linear with query: {graphql_query}")

            response = _make_query(graphql_query, self.linear_api_key)
            response_json = response.json()
            logger.debug(f"Raw response from Linear: {response_json}")
            edges = response_json["data"]["issues"]["edges"]

            documents: list[Document] = []
            for edge in edges:
                node = edge["node"]
                # Create sections for description and comments
                sections = [
                    TextSection(
                        link=node["url"],
                        text=node["description"] or "",
                    )
                ]

                # Add comment sections
                for comment in node["comments"]["nodes"]:
                    sections.append(
                        TextSection(
                            link=node["url"],
                            text=comment["body"] or "",
                        )
                    )

                # Cast the sections list to the expected type
                typed_sections = cast(list[TextSection | ImageSection], sections)

                documents.append(
                    Document(
                        id=node["id"],
                        sections=typed_sections,
                        source=DocumentSource.LINEAR,
                        semantic_identifier=f"[{node['identifier']}] {node['title']}",
                        title=node["title"],
                        doc_updated_at=time_str_to_utc(node["updatedAt"]),
                        metadata={
                            k: str(v)
                            for k, v in {
                                "team": (node.get("team") or {}).get("name"),
                                "creator": node.get("creator"),
                                "assignee": node.get("assignee"),
                                "state": (node.get("state") or {}).get("name"),
                                "priority": node.get("priority"),
                                "estimate": node.get("estimate"),
                                "started_at": node.get("startedAt"),
                                "completed_at": node.get("completedAt"),
                                "created_at": node.get("createdAt"),
                                "due_date": node.get("dueDate"),
                            }.items()
                            if v is not None
                        },
                    )
                )
            yield documents

            endCursor = response_json["data"]["issues"]["pageInfo"]["endCursor"]
            has_more = response_json["data"]["issues"]["pageInfo"]["hasNextPage"]

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._process_issues()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_time = datetime.fromtimestamp(start, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end, tz=timezone.utc)

        yield from self._process_issues(start_str=start_time, end_str=end_time)


if __name__ == "__main__":
    connector = LinearConnector()
    connector.load_credentials({"linear_api_key": os.environ["LINEAR_API_KEY"]})

    document_batches = connector.load_from_state()
    print(next(document_batches))
