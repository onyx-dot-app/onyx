from collections.abc import Generator
from itertools import chain
from typing import Any
from typing import cast

import requests
from bs4 import BeautifulSoup
from dateutil import parser
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger


logger = setup_logger()


_PRODUCT_BOARD_BASE_URL = "https://api.productboard.com"


class ProductboardApiError(Exception):
    pass


class ProductboardConnector(PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.batch_size = batch_size
        self.access_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.access_token = credentials["productboard_access_token"]
        return None

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Version": "1",
        }

    @staticmethod
    def _parse_description_html(description_html: str) -> str:
        soup = BeautifulSoup(description_html, "html.parser")
        return soup.get_text()

    @staticmethod
    def _get_owner_email(productboard_obj: dict[str, Any]) -> str | None:
        owner_dict = cast(dict[str, str] | None, productboard_obj.get("owner"))
        if not owner_dict:
            return None
        return owner_dict.get("email")

    def _fetch_documents(
        self,
        initial_link: str,
    ) -> Generator[dict[str, Any], None, None]:
        headers = self._build_headers()

        @retry(tries=3, delay=1, backoff=2)
        def fetch(link: str) -> dict[str, Any]:
            response = requests.get(link, headers=headers)
            if not response.ok:
                # rate-limiting is at 50 requests per second.
                # The delay in this retry should handle this while this is
                # not parallelized.
                raise ProductboardApiError(
                    "Failed to fetch from productboard - status code:"
                    f" {response.status_code} - response: {response.text}"
                )

            return response.json()

        curr_link = initial_link
        while True:
            response_json = fetch(curr_link)
            for entity in response_json["data"]:
                yield entity

            curr_link = response_json.get("links", {}).get("next")
            if not curr_link:
                break

    def _get_features(self) -> Generator[Document, None, None]:
        """A Feature is like a ticket in Jira"""
        for feature in self._fetch_documents(
            initial_link=f"{_PRODUCT_BOARD_BASE_URL}/features"
        ):
            owner = self._get_owner_email(feature)
            experts = [BasicExpertInfo(email=owner)] if owner else None

            metadata: dict[str, str | list[str]] = {}
            entity_type = feature.get("type", "feature")
            if entity_type:
                metadata["entity_type"] = str(entity_type)

            status = feature.get("status", {}).get("name")
            if status:
                metadata["status"] = str(status)

            yield Document(
                id=feature["id"],
                sections=[
                    TextSection(
                        link=feature["links"]["html"],
                        text=self._parse_description_html(feature["description"]),
                    )
                ],
                semantic_identifier=feature["name"],
                source=DocumentSource.PRODUCTBOARD,
                doc_updated_at=time_str_to_utc(feature["updatedAt"]),
                primary_owners=experts,
                metadata=metadata,
            )

    def _get_components(self) -> Generator[Document, None, None]:
        """A Component is like an epic in Jira. It contains Features"""
        for component in self._fetch_documents(
            initial_link=f"{_PRODUCT_BOARD_BASE_URL}/components"
        ):
            owner = self._get_owner_email(component)
            experts = [BasicExpertInfo(email=owner)] if owner else None

            yield Document(
                id=component["id"],
                sections=[
                    TextSection(
                        link=component["links"]["html"],
                        text=self._parse_description_html(component["description"]),
                    )
                ],
                semantic_identifier=component["name"],
                source=DocumentSource.PRODUCTBOARD,
                doc_updated_at=time_str_to_utc(component["updatedAt"]),
                primary_owners=experts,
                metadata={
                    "entity_type": "component",
                },
            )

    def _get_products(self) -> Generator[Document, None, None]:
        """A Product is the highest level of organization.
        A Product contains components, which contains features."""
        for product in self._fetch_documents(
            initial_link=f"{_PRODUCT_BOARD_BASE_URL}/products"
        ):
            owner = self._get_owner_email(product)
            experts = [BasicExpertInfo(email=owner)] if owner else None

            yield Document(
                id=product["id"],
                sections=[
                    TextSection(
                        link=product["links"]["html"],
                        text=self._parse_description_html(product["description"]),
                    )
                ],
                semantic_identifier=product["name"],
                source=DocumentSource.PRODUCTBOARD,
                doc_updated_at=time_str_to_utc(product["updatedAt"]),
                primary_owners=experts,
                metadata={
                    "entity_type": "product",
                },
            )

    def _get_objectives(self) -> Generator[Document, None, None]:
        for objective in self._fetch_documents(
            initial_link=f"{_PRODUCT_BOARD_BASE_URL}/objectives"
        ):
            owner = self._get_owner_email(objective)
            experts = [BasicExpertInfo(email=owner)] if owner else None

            metadata: dict[str, str | list[str]] = {
                "entity_type": "objective",
            }
            if objective.get("state"):
                metadata["state"] = str(objective["state"])

            yield Document(
                id=objective["id"],
                sections=[
                    TextSection(
                        link=objective["links"]["html"],
                        text=self._parse_description_html(objective["description"]),
                    )
                ],
                semantic_identifier=objective["name"],
                source=DocumentSource.PRODUCTBOARD,
                doc_updated_at=time_str_to_utc(objective["updatedAt"]),
                primary_owners=experts,
                metadata=metadata,
            )

    def _is_updated_at_out_of_time_range(
        self,
        document: Document,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> bool:
        updated_at = cast(str, document.metadata.get("updated_at", ""))
        if updated_at:
            updated_at_datetime = parser.parse(updated_at)
            if (
                updated_at_datetime.timestamp() < start
                or updated_at_datetime.timestamp() > end
            ):
                return True
        else:
            logger.debug(f"Unable to find updated_at for document '{document.id}'")

        return False

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.access_token is None:
            raise PermissionError(
                "Access token is not set up, was load_credentials called?"
            )

        document_batch: list[Document] = []

        # NOTE: there is a concept of a "Note" in productboard, however
        # there is no read API for it atm. Additionally, comments are not
        # included with features. Finally, "Releases" are not fetched atm,
        # since they do not provide an updatedAt.
        feature_documents = self._get_features()
        component_documents = self._get_components()
        product_documents = self._get_products()
        objective_documents = self._get_objectives()
        for document in chain(
            feature_documents,
            component_documents,
            product_documents,
            objective_documents,
        ):
            # skip documents that are not in the time range
            if self._is_updated_at_out_of_time_range(document, start, end):
                continue

            document_batch.append(document)
            if len(document_batch) >= self.batch_size:
                yield document_batch
                document_batch = []

        if document_batch:
            yield document_batch


if __name__ == "__main__":
    import os
    import time

    connector = ProductboardConnector()
    connector.load_credentials(
        {
            "productboard_access_token": os.environ["PRODUCTBOARD_ACCESS_TOKEN"],
        }
    )

    current = time.time()
    one_year_ago = current - 24 * 60 * 60 * 360
    latest_docs = connector.poll_source(one_year_ago, current)
    print(next(latest_docs))
