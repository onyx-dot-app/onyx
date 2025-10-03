import json
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urljoin

import requests
from dateutil import parser

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger


logger = setup_logger()


# Fairly generous retry because it's not understood why occasionally GraphQL requests fail even with timeout > 1 min
SLAB_GRAPHQL_MAX_TRIES = 10
SLAB_API_URL = "https://api.slab.com/v1/graphql"

_SLIM_BATCH_SIZE = 1000


def run_graphql_request(
    graphql_query: dict, bot_token: str, max_tries: int = SLAB_GRAPHQL_MAX_TRIES
) -> str:
    headers = {"Authorization": bot_token, "Content-Type": "application/json"}

    for try_count in range(max_tries):
        try:
            response = requests.post(
                SLAB_API_URL, headers=headers, json=graphql_query, timeout=60
            )
            response.raise_for_status()

            if response.status_code != 200:
                raise ValueError(f"GraphQL query failed: {graphql_query}")

            return response.text

        except (requests.exceptions.Timeout, ValueError) as e:
            if try_count < max_tries - 1:
                logger.warning("A Slab GraphQL error occurred. Retrying...")
                continue

            if isinstance(e, requests.exceptions.Timeout):
                raise TimeoutError("Slab API timed out after 3 attempts")
            else:
                raise ValueError("Slab GraphQL query failed after 3 attempts")

    raise RuntimeError(
        "Unexpected execution from Slab Connector. This should not happen."
    )  # for static checker


def get_all_post_ids(bot_token: str) -> list[str]:
    query = """
        query GetAllPostIds {
            organization {
                posts {
                    id
                }
            }
        }
        """

    graphql_query = {"query": query}

    results = json.loads(run_graphql_request(graphql_query, bot_token))
    posts = results["data"]["organization"]["posts"]
    return [post["id"] for post in posts]


def get_post_by_id(post_id: str, bot_token: str) -> dict[str, str]:
    query = """
        query GetPostById($postId: ID!) {
            post(id: $postId) {
                title
                content
                linkAccess
                updatedAt
            }
        }
        """
    graphql_query = {"query": query, "variables": {"postId": post_id}}
    results = json.loads(run_graphql_request(graphql_query, bot_token))
    return results["data"]["post"]


def iterate_post_batches(
    batch_size: int, bot_token: str
) -> Generator[list[dict[str, str]], None, None]:
    """This may not be safe to use, not sure if page edits will change the order of results"""
    query = """
        query IteratePostBatches($query: String!, $first: Int, $types: [SearchType], $after: String) {
            search(query: $query, first: $first, types: $types, after: $after) {
                edges {
                    node {
                        ... on PostSearchResult {
                            post {
                                id
                                title
                                content
                                updatedAt
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    """
    pagination_start = None
    exists_more_pages = True
    while exists_more_pages:
        graphql_query = {
            "query": query,
            "variables": {
                "query": "",
                "first": batch_size,
                "types": ["POST"],
                "after": pagination_start,
            },
        }
        results = json.loads(run_graphql_request(graphql_query, bot_token))
        pagination_start = results["data"]["search"]["pageInfo"]["endCursor"]
        hits = results["data"]["search"]["edges"]

        posts = [hit["node"] for hit in hits]
        if posts:
            yield posts

        exists_more_pages = results["data"]["search"]["pageInfo"]["hasNextPage"]


def get_slab_url_from_title_id(base_url: str, title: str, page_id: str) -> str:
    """This is not a documented approach but seems to be the way it works currently
    May be subject to change without notification"""
    title = (
        title.replace("[", "")
        .replace("]", "")
        .replace(":", "")
        .replace(" ", "-")
        .lower()
    )
    url_id = title + "-" + page_id
    return urljoin(urljoin(base_url, "posts/"), url_id)


class SlabConnector(LoadConnector, PollConnector, SlimConnectorWithPermSync):
    def __init__(
        self,
        base_url: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.base_url = base_url
        self.batch_size = batch_size
        self._slab_bot_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._slab_bot_token = credentials["slab_bot_token"]
        return None

    @property
    def slab_bot_token(self) -> str:
        if self._slab_bot_token is None:
            raise ConnectorMissingCredentialError("Slab")
        return self._slab_bot_token

    def _iterate_posts(
        self, time_filter: Callable[[datetime], bool] | None = None
    ) -> GenerateDocumentsOutput:
        doc_batch: list[Document] = []

        if self.slab_bot_token is None:
            raise ConnectorMissingCredentialError("Slab")

        all_post_ids: list[str] = get_all_post_ids(self.slab_bot_token)

        for post_id in all_post_ids:
            post = get_post_by_id(post_id, self.slab_bot_token)
            last_modified = parser.parse(post["updatedAt"])
            if time_filter is not None and not time_filter(last_modified):
                continue

            page_url = get_slab_url_from_title_id(self.base_url, post["title"], post_id)

            content_text = ""
            contents = json.loads(post["content"])
            for content_segment in contents:
                insert = content_segment.get("insert")
                if insert and isinstance(insert, str):
                    content_text += insert

            doc_batch.append(
                Document(
                    id=post_id,  # can't be url as this changes with the post title
                    sections=[TextSection(link=page_url, text=content_text)],
                    source=DocumentSource.SLAB,
                    semantic_identifier=post["title"],
                    metadata={},
                )
            )

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._iterate_posts()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_time = datetime.fromtimestamp(start, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end, tz=timezone.utc)

        yield from self._iterate_posts(
            time_filter=lambda t: start_time <= t <= end_time
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        slim_doc_batch: list[SlimDocument] = []
        for post_id in get_all_post_ids(self.slab_bot_token):
            slim_doc_batch.append(
                SlimDocument(
                    id=post_id,
                )
            )
            if len(slim_doc_batch) >= _SLIM_BATCH_SIZE:
                yield slim_doc_batch
                slim_doc_batch = []
        if slim_doc_batch:
            yield slim_doc_batch
