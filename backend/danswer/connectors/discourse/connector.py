import time
import urllib.parse
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from pydantic import BaseModel
from requests import Response

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from danswer.connectors.cross_connector_utils.retry_wrapper import retry_builder
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import BasicExpertInfo
from danswer.connectors.models import ConnectorMissingCredentialError
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.file_processing.html_utils import parse_html_page_basic
from danswer.utils.logger import setup_logger

logger = setup_logger()


class DiscoursePerms(BaseModel):
    api_key: str
    api_username: str


@retry_builder()
def discourse_request(
    endpoint: str, perms: DiscoursePerms, params: dict | None = None
) -> Response:
    headers = {"Api-Key": perms.api_key, "Api-Username": perms.api_username}

    response = requests.get(endpoint, headers=headers, params=params)
    response.raise_for_status()

    return response


class DiscourseConnector(PollConnector):
    def __init__(
        self,
        base_url: str,
        categories: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        parsed_url = urllib.parse.urlparse(base_url)
        if not parsed_url.scheme:
            base_url = "https://" + base_url
        self.base_url = base_url

        self.categories = [c.lower() for c in categories] if categories else []
        self.category_id_map: dict[int, str] = {}

        self.batch_size = batch_size

        self.permissions: DiscoursePerms | None = None

    def _get_categories_map(
        self,
    ) -> None:
        assert self.permissions is not None
        categories_endpoint = urllib.parse.urljoin(self.base_url, "categories.json")
        response = discourse_request(
            endpoint=categories_endpoint,
            perms=self.permissions,
            params={"include_subcategories": True},
        )
        categories = response.json()["category_list"]["categories"]

        self.category_id_map = {
            category["id"]: category["name"]
            for category in categories
            if not self.categories or category["name"].lower() in self.categories
        }

    def _get_latest_topics(
        self, start: datetime | None, end: datetime | None
    ) -> list[int]:
        assert self.permissions is not None
        topic_ids = []

        valid_categories = set(self.category_id_map.keys())

        latest_endpoint = urllib.parse.urljoin(self.base_url, "latest.json")
        response = discourse_request(endpoint=latest_endpoint, perms=self.permissions)
        topics = response.json()["topic_list"]["topics"]
        for topic in topics:
            last_time = topic.get("last_posted_at")
            if not last_time:
                continue
            last_time_dt = time_str_to_utc(last_time)

            if start and start > last_time_dt:
                continue
            if end and end < last_time_dt:
                continue

            if (
                self.categories
                and valid_categories
                and topic.get("category_id") not in valid_categories
            ):
                continue

            topic_ids.append(topic["id"])

        return topic_ids

    def _get_doc_from_topic(self, topic_id: int) -> Document:
        assert self.permissions is not None
        topic_endpoint = urllib.parse.urljoin(self.base_url, f"t/{topic_id}.json")
        response = discourse_request(
            endpoint=topic_endpoint,
            perms=self.permissions,
        )
        topic = response.json()

        topic_url = urllib.parse.urljoin(self.base_url, f"t/{topic['slug']}")

        sections = []
        poster = None
        responders = []
        seen_names = set()
        for ind, post in enumerate(topic["post_stream"]["posts"]):
            if ind == 0:
                poster_name = post.get("name")
                if poster_name:
                    seen_names.add(poster_name)
                    poster = BasicExpertInfo(display_name=poster_name)
            else:
                responder_name = post.get("name")
                if responder_name and responder_name not in seen_names:
                    seen_names.add(responder_name)
                    responders.append(BasicExpertInfo(display_name=responder_name))

            sections.append(
                Section(link=topic_url, text=parse_html_page_basic(post["cooked"]))
            )
        category_name = self.category_id_map.get(topic["category_id"])

        metadata: dict[str, str | list[str]] = (
            {
                "category": category_name,
            }
            if category_name
            else {}
        )

        if topic.get("tags"):
            metadata["tags"] = topic["tags"]

        doc = Document(
            id="_".join([DocumentSource.DISCOURSE.value, str(topic["id"])]),
            sections=sections,
            source=DocumentSource.DISCOURSE,
            semantic_identifier=topic["title"],
            doc_updated_at=time_str_to_utc(topic["last_posted_at"]),
            primary_owners=[poster] if poster else None,
            secondary_owners=responders or None,
            metadata=metadata,
        )
        return doc

    def _yield_discourse_documents(
        self, topic_ids: list[int]
    ) -> GenerateDocumentsOutput:
        doc_batch: list[Document] = []
        for topic_id in topic_ids:
            doc_batch.append(self._get_doc_from_topic(topic_id))

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.permissions = DiscoursePerms(
            api_key=credentials["discourse_api_key"],
            api_username=credentials["discourse_api_username"],
        )

        return None

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.permissions is None:
            raise ConnectorMissingCredentialError("Discourse")
        start_datetime = datetime.utcfromtimestamp(start).replace(tzinfo=timezone.utc)
        end_datetime = datetime.utcfromtimestamp(end).replace(tzinfo=timezone.utc)

        self._get_categories_map()

        latest_topic_ids = self._get_latest_topics(
            start=start_datetime, end=end_datetime
        )

        yield from self._yield_discourse_documents(latest_topic_ids)


if __name__ == "__main__":
    import os

    connector = DiscourseConnector(base_url=os.environ["DISCOURSE_BASE_URL"])
    connector.load_credentials(
        {
            "discourse_api_key": os.environ["DISCOURSE_API_KEY"],
            "discourse_api_username": os.environ["DISCOURSE_API_USERNAME"],
        }
    )

    current = time.time()
    one_year_ago = current - 24 * 60 * 60 * 360

    latest_docs = connector.poll_source(one_year_ago, current)

    print(next(latest_docs))
