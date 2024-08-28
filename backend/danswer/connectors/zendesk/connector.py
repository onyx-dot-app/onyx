from typing import Any

import requests
from retry import retry
from zenpy import Zenpy  # type: ignore
from zenpy.lib.api_objects.help_centre_objects import Article  # type: ignore

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.app_configs import ZENDESK_CONNECTOR_SKIP_ARTICLE_LABELS
from danswer.configs.constants import DocumentSource
from danswer.connectors.cross_connector_utils.miscellaneous_utils import (
    time_str_to_utc,
)
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import BasicExpertInfo
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.file_processing.html_utils import parse_html_page_basic


def _article_to_document(article: Article, content_tags: dict[str, str]) -> Document:
    author = BasicExpertInfo(
        display_name=article.author.name, email=article.author.email
    )
    update_time = time_str_to_utc(article.updated_at)

    # build metadata
    metadata: dict[str, str | list[str]] = {
        "labels": [str(label) for label in article.label_names if label],
        "content_tags": [
            content_tags[tag_id]
            for tag_id in article.content_tag_ids
            if tag_id in content_tags
        ],
    }

    # remove empty values
    metadata = {k: v for k, v in metadata.items() if v}

    return Document(
        id=f"article:{article.id}",
        sections=[
            Section(link=article.html_url, text=parse_html_page_basic(article.body))
        ],
        source=DocumentSource.ZENDESK,
        semantic_identifier=article.title,
        doc_updated_at=update_time,
        primary_owners=[author],
        metadata=metadata,
    )


class ZendeskClientNotSetUpError(PermissionError):
    def __init__(self) -> None:
        super().__init__("Zendesk Client is not set up, was load_credentials called?")


class ZendeskConnector(LoadConnector, PollConnector):
    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self.zendesk_client: Zenpy | None = None
        self.content_tags: dict[str, str] = {}

    @retry(tries=3, delay=2, backoff=2)
    def _set_content_tags(
        self, subdomain: str, email: str, token: str, page_size: int = 30
    ) -> None:
        # Construct the base URL
        base_url = f"https://{subdomain}.zendesk.com/api/v2/guide/content_tags"

        # Set up authentication
        auth = (f"{email}/token", token)

        # Set up pagination parameters
        params = {"page[size]": page_size}

        try:
            while True:
                # Make the GET request
                response = requests.get(base_url, auth=auth, params=params)

                # Check if the request was successful
                if response.status_code == 200:
                    data = response.json()
                    content_tag_list = data.get("records", [])
                    for tag in content_tag_list:
                        self.content_tags[tag["id"]] = tag["name"]

                    # Check if there are more pages
                    if data.get("meta", {}).get("has_more", False):
                        params["page[after]"] = data["meta"]["after_cursor"]
                    else:
                        break
                else:
                    raise Exception(f"Error: {response.status_code}\n{response.text}")
        except Exception as e:
            raise Exception(f"Error fetching content tags: {str(e)}")

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # Subdomain is actually the whole URL
        subdomain = (
            credentials["zendesk_subdomain"]
            .replace("https://", "")
            .split(".zendesk.com")[0]
        )

        self.zendesk_client = Zenpy(
            subdomain=subdomain,
            email=credentials["zendesk_email"],
            token=credentials["zendesk_token"],
        )
        self._set_content_tags(
            subdomain,
            credentials["zendesk_email"],
            credentials["zendesk_token"],
        )
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self.poll_source(None, None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        if self.zendesk_client is None:
            raise ZendeskClientNotSetUpError()

        articles = (
            self.zendesk_client.help_center.articles(cursor_pagination=True)
            if start is None
            else self.zendesk_client.help_center.articles.incremental(
                start_time=int(start)
            )
        )
        doc_batch = []
        for article in articles:
            if (
                article.body is None
                or article.draft
                or any(
                    label in ZENDESK_CONNECTOR_SKIP_ARTICLE_LABELS
                    for label in article.label_names
                )
            ):
                continue

            doc_batch.append(_article_to_document(article, self.content_tags))
            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch.clear()

        if doc_batch:
            yield doc_batch


if __name__ == "__main__":
    import os
    import time

    connector = ZendeskConnector()
    connector.load_credentials(
        {
            "zendesk_subdomain": os.environ["ZENDESK_SUBDOMAIN"],
            "zendesk_email": os.environ["ZENDESK_EMAIL"],
            "zendesk_token": os.environ["ZENDESK_TOKEN"],
        }
    )

    current = time.time()
    one_day_ago = current - 24 * 60 * 60  # 1 day
    document_batches = connector.poll_source(one_day_ago, current)

    print(next(document_batches))
