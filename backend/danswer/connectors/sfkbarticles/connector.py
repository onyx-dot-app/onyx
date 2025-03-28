import os
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Tuple

import requests

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import BasicExpertInfo
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.connectors.sfkbarticles.utils import extract_dict_text
from danswer.utils.logger import setup_logger

ID_PREFIX = "SALESFORCE_"
AUTH_URL = "https://login.salesforce.com/services/oauth2/token"

logger = setup_logger()


class SfKbArticlesConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        requested_objects: list[str] = [],
    ) -> None:
        self.batch_size = batch_size
        self.product_component_list = (
            [obj.strip() for obj in requested_objects[0].split(",")]
            if requested_objects
            else None
        )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.client_id = credentials["sf_client_id"]
        self.client_secret = credentials["sf_client_secret"]
        self.username = credentials["sf_username"]
        self.password = credentials["sf_password"]

        self.access_token, self.instance_url = self._get_access_token()

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _get_access_token(self) -> Tuple[str, str]:
        """
        Authenticates with Salesforce and retrieves the access token & instance URL.
        """
        payload = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": f"{self.password}",
        }
        response = requests.post(AUTH_URL, data=payload)
        if response.status_code != 200:
            logger.error(f"Authentication failed: {response.text}")
            raise Exception("Failed to authenticate with Salesforce.")

        data = response.json()
        logger.info("Successfully authenticated with Salesforce.")
        return data["access_token"], data["instance_url"]

    def _convert_object_instance_to_document(
        self, object_dict: dict[str, Any]
    ) -> Document:
        salesforce_id = object_dict["Id"]
        danswer_salesforce_id = f"{ID_PREFIX}{salesforce_id}"
        extracted_link = f"{self.instance_url}/{salesforce_id}"
        extracted_doc_updated_at = time_str_to_utc(object_dict["LastModifiedDate"])
        extracted_object_text = extract_dict_text(object_dict)
        extracted_semantic_identifier = object_dict.get("Title", "Unknown Object")
        extracted_primary_owners = [
            BasicExpertInfo(
                display_name=self._get_name_from_id(object_dict["LastModifiedById"])
            )
        ]

        doc = Document(
            id=danswer_salesforce_id,
            sections=[Section(link=extracted_link, text=extracted_object_text)],
            source=DocumentSource.SFKBARTICLES,
            semantic_identifier=extracted_semantic_identifier,
            doc_updated_at=extracted_doc_updated_at,
            primary_owners=extracted_primary_owners,
            metadata={},
        )
        return doc

    def _get_name_from_id(self, id: str) -> str:
        """
        Fetches the name of a Salesforce user based on their ID.
        """
        query = f"SELECT Name FROM User WHERE Id = '{id}'"
        url = f"{self.instance_url}/services/data/v56.0/query"
        params = {"q": query}

        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code != 200:
            logger.error(f"Failed to fetch name for ID {id}: {response.text}")
            return "Unknown"

        data = response.json()
        records = data.get("records", [])
        if not records:
            logger.warning(f"No name found for ID {id}")
            return "Unknown"

        return records[0].get("Name", "Unknown")

    def build_salesforce_query(
        self,
        parent_objects: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> str:
        """
        Builds the Salesforce query dynamically.
        If product_component_list is empty, it fetches all Product_Component__c values.
        Otherwise, it filters using the provided product_component_list.
        """
        if not parent_objects:
            product_filter = ""  # No filter, fetch all
        else:
            product_components_str = ", ".join(
                [
                    f"'{component.strip()}'"
                    for component in parent_objects
                    if component.strip()
                ]
            )
            product_filter = f"AND Product_Component__c IN ({product_components_str})"

        query = f"""
        SELECT
            Id,
            Title,
            Summary,
            Product_Component__c,
            Product_Component_Version__c,
            Question_Problem__c,
            Resolution__c,
            Sub_Component__c,
            IsVisibleInPkb,
            IsVisibleInCsp,
            IsVisibleInPrm,
            ArticleCreatedDate,
            ArticleNumber,
            CreatedDate,
            ArticleTotalViewCount,
            FirstPublishedDate,
            IsDeleted,
            IsLatestVersion,
            Language,
            LastModifiedDate,
            LastModifiedById,
            LastPublishedDate,
            Orchestrator_Version__c,
            Studio_Version__c
        FROM Knowledge__kav
        WHERE Language='en_US'
        AND PublishStatus = 'Online'
        AND IsDeleted = FALSE
        {product_filter}
        """.strip()

        if start:
            start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            query += f" AND LastModifiedDate >= {start_str}"
        if end:
            end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            query += f" AND LastModifiedDate <= {end_str}"

        return query

    def _fetch_from_salesforce(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> GenerateDocumentsOutput:
        query = self.build_salesforce_query(self.product_component_list, start, end)
        doc_batch: list[Document] = []
        query_results: dict = {}

        url = f"{self.instance_url}/services/data/v56.0/query"
        params = {"q": query}
        query_result = requests.get(
            url, headers=self.headers, params=params if "q" in params else None
        )

        while url:
            query_result = requests.get(
                url, headers=self.headers, params=params if "q" in params else None
            )
            data = query_result.json()

            if isinstance(data, list):
                error_message = "; ".join(
                    error.get("message", "Unknown error") for error in data
                )
                raise Exception(f"Salesforce API error: {error_message}")

            if "records" in data:
                for record_dict in data["records"]:
                    query_results.setdefault(record_dict["Id"], {}).update(record_dict)

            url = data.get("nextRecordsUrl", None)
            if url:
                url = f"{self.instance_url}{url}"

        for combined_object_dict in query_results.values():
            doc_batch.append(
                self._convert_object_instance_to_document(combined_object_dict)
            )
            if len(doc_batch) > self.batch_size:
                yield doc_batch
                doc_batch = []

        yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_from_salesforce()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        return self._fetch_from_salesforce(start=start_datetime, end=end_datetime)


if __name__ == "__main__":
    connector = SfKbArticlesConnector(
        requested_objects=os.environ["REQUESTED_OBJECTS"].split(",")
    )

    connector.load_credentials(
        {
            "sf_client_id": os.environ["SF_CLIENT_ID"],
            "sf_client_secret": os.environ["SF_CLIENT_SECRET"],
            "sf_username": os.environ["SF_USERNAME"],
            "sf_password": os.environ["SF_PASSWORD"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
