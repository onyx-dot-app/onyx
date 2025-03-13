import json
from datetime import datetime
from datetime import timezone
from typing import Any

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.utils.logger import setup_logger


logger = setup_logger()

# Potential Improvements
# 1. Support fetching per collection via collection token (configured at connector creation)
GURU_API_BASE = "https://api.getguru.com/api/v1/"
GURU_QUERY_ENDPOINT = GURU_API_BASE + "search/query"
GURU_CARDS_URL = "https://app.getguru.com/card/"


def unixtime_to_guru_time_str(unix_time: SecondsSinceUnixEpoch) -> str:
    date_obj = datetime.fromtimestamp(unix_time, tz=timezone.utc)
    date_str = date_obj.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    tz_str = date_obj.strftime("%z")
    return date_str + tz_str


class GuruConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        guru_user: str | None = None,
        guru_user_token: str | None = None,
    ) -> None:
        self.batch_size = batch_size
        self.guru_user = guru_user
        self.guru_user_token = guru_user_token

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.guru_user = credentials["guru_user"]
        self.guru_user_token = credentials["guru_user_token"]
        return None

    def _process_cards(
        self, start_str: str | None = None, end_str: str | None = None
    ) -> GenerateDocumentsOutput:
        if self.guru_user is None or self.guru_user_token is None:
            raise ConnectorMissingCredentialError("Guru")

        doc_batch: list[Document] = []

        session = requests.Session()
        session.auth = (self.guru_user, self.guru_user_token)

        params: dict[str, str | int] = {"maxResults": self.batch_size}

        if start_str is not None and end_str is not None:
            params["q"] = f"lastModified >= {start_str} AND lastModified < {end_str}"

        current_url = GURU_QUERY_ENDPOINT  # This is how they handle pagination, a different url will be provided
        while True:
            response = session.get(current_url, params=params)
            response.raise_for_status()

            if response.status_code == 204:
                break

            cards = json.loads(response.text)
            for card in cards:
                title = card["preferredPhrase"]
                link = GURU_CARDS_URL + card["slug"]
                content_text = parse_html_page_basic(card["content"])
                last_updated = time_str_to_utc(card["lastModified"])
                last_verified = (
                    time_str_to_utc(card.get("lastVerified"))
                    if card.get("lastVerified")
                    else None
                )

                # For Onyx, we decay document score overtime, either last_updated or
                # last_verified is a good enough signal for the document's recency
                latest_time = (
                    max(last_verified, last_updated) if last_verified else last_updated
                )

                metadata_dict: dict[str, str | list[str]] = {}
                tags = [tag.get("value") for tag in card.get("tags", [])]
                if tags:
                    metadata_dict["tags"] = tags

                boards = [board.get("title") for board in card.get("boards", [])]
                if boards:
                    # In UI it's called Folders
                    metadata_dict["folders"] = boards

                collection = card.get("collection", {})
                if collection:
                    metadata_dict["collection_name"] = collection.get("name", "")

                owner = card.get("owner", {})
                author = None
                if owner:
                    author = BasicExpertInfo(
                        email=owner.get("email"),
                        first_name=owner.get("firstName"),
                        last_name=owner.get("lastName"),
                    )

                doc_batch.append(
                    Document(
                        id=card["id"],
                        sections=[TextSection(link=link, text=content_text)],
                        source=DocumentSource.GURU,
                        semantic_identifier=title,
                        doc_updated_at=latest_time,
                        primary_owners=[author] if author is not None else None,
                        # Can add verifies and commenters later
                        metadata=metadata_dict,
                    )
                )

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

            if not hasattr(response, "links") or not response.links:
                break
            current_url = response.links["next-page"]["url"]

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_cards()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_time = unixtime_to_guru_time_str(start)
        end_time = unixtime_to_guru_time_str(end)

        return self._process_cards(start_time, end_time)


if __name__ == "__main__":
    import os

    connector = GuruConnector()
    connector.load_credentials(
        {
            "guru_user": os.environ["GURU_USER"],
            "guru_user_token": os.environ["GURU_USER_TOKEN"],
        }
    )

    latest_docs = connector.load_from_state()
    print(next(latest_docs))
