import os
from collections.abc import Iterator
from datetime import datetime
from datetime import UTC
from typing import Any

from simple_salesforce import Salesforce
from simple_salesforce import SFType

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.connectors.models import SlimDocument
from onyx.connectors.salesforce.doc_conversion import extract_dict_text
from onyx.utils.logger import setup_logger


# TODO: this connector does not work well at large scales
# the large query against a large Salesforce instance has been reported to take 1.5 hours.
# Additionally it seems to eat up more memory over time if the connection is long running (again a scale issue).


DEFAULT_PARENT_OBJECT_TYPES = ["Account"]
MAX_QUERY_LENGTH = 10000  # max query length is 20,000 characters
ID_PREFIX = "SALESFORCE_"

logger = setup_logger()


def _build_time_filter_for_salesforce(
    start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
) -> str:
    if start is None or end is None:
        return ""
    start_datetime = datetime.fromtimestamp(start, UTC)
    end_datetime = datetime.fromtimestamp(end, UTC)
    return (
        f" WHERE LastModifiedDate > {start_datetime.isoformat()} "
        f"AND LastModifiedDate < {end_datetime.isoformat()}"
    )


class SalesforceConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        requested_objects: list[str] = [],
    ) -> None:
        self.batch_size = batch_size
        self._sf_client: Salesforce | None = None
        self.parent_object_list = (
            [obj.capitalize() for obj in requested_objects]
            if requested_objects
            else DEFAULT_PARENT_OBJECT_TYPES
        )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._sf_client = Salesforce(
            username=credentials["sf_username"],
            password=credentials["sf_password"],
            security_token=credentials["sf_security_token"],
        )
        return None

    @property
    def sf_client(self) -> Salesforce:
        if self._sf_client is None:
            raise ConnectorMissingCredentialError("Salesforce")
        return self._sf_client

    def _get_sf_type_object_json(self, type_name: str) -> Any:
        sf_object = SFType(
            type_name, self.sf_client.session_id, self.sf_client.sf_instance
        )
        return sf_object.describe()

    def _get_name_from_id(self, id: str) -> str:
        try:
            user_object_info = self.sf_client.query(
                f"SELECT Name FROM User WHERE Id = '{id}'"
            )
            name = user_object_info.get("Records", [{}])[0].get("Name", "Null User")
            return name
        except Exception:
            logger.warning(f"Couldnt find name for object id: {id}")
            return "Null User"

    def _convert_object_instance_to_document(
        self, object_dict: dict[str, Any]
    ) -> Document:
        salesforce_id = object_dict["Id"]
        onyx_salesforce_id = f"{ID_PREFIX}{salesforce_id}"
        extracted_link = f"https://{self.sf_client.sf_instance}/{salesforce_id}"
        extracted_doc_updated_at = time_str_to_utc(object_dict["LastModifiedDate"])
        extracted_object_text = extract_dict_text(object_dict)
        extracted_semantic_identifier = object_dict.get("Name", "Unknown Object")
        extracted_primary_owners = [
            BasicExpertInfo(
                display_name=self._get_name_from_id(object_dict["LastModifiedById"])
            )
        ]

        doc = Document(
            id=onyx_salesforce_id,
            sections=[Section(link=extracted_link, text=extracted_object_text)],
            source=DocumentSource.SALESFORCE,
            semantic_identifier=extracted_semantic_identifier,
            doc_updated_at=extracted_doc_updated_at,
            primary_owners=extracted_primary_owners,
            metadata={},
        )
        return doc

    def _is_valid_child_object(self, child_relationship: dict) -> bool:
        if not child_relationship["childSObject"]:
            return False
        if not child_relationship["relationshipName"]:
            return False

        sf_type = child_relationship["childSObject"]
        object_description = self._get_sf_type_object_json(sf_type)
        if not object_description["queryable"]:
            return False

        try:
            query = f"SELECT Count() FROM {sf_type} LIMIT 1"
            result = self.sf_client.query(query)
            if result["totalSize"] == 0:
                return False
        except Exception as e:
            logger.warning(f"Object type {sf_type} doesn't support query: {e}")
            return False

        if child_relationship["field"]:
            if child_relationship["field"] == "RelatedToId":
                return False
        else:
            return False

        return True

    def _get_all_children_of_sf_type(self, sf_type: str) -> list[dict]:
        object_description = self._get_sf_type_object_json(sf_type)

        children_objects: list[dict] = []
        for child_relationship in object_description["childRelationships"]:
            if self._is_valid_child_object(child_relationship):
                children_objects.append(
                    {
                        "relationship_name": child_relationship["relationshipName"],
                        "object_type": child_relationship["childSObject"],
                    }
                )
        return children_objects

    def _get_all_fields_for_sf_type(self, sf_type: str) -> list[str]:
        object_description = self._get_sf_type_object_json(sf_type)

        fields = [
            field.get("name")
            for field in object_description["fields"]
            if field.get("type", "base64") != "base64"
        ]

        return fields

    def _generate_query_per_parent_type(self, parent_sf_type: str) -> Iterator[str]:
        """
        This function takes in an object_type and generates query(s) designed to grab
        information associated to objects of that type.
        It does that by getting all the fields of the parent object type.
        Then it gets all the child objects of that object type and all the fields of
        those children as well.
        """
        parent_fields = self._get_all_fields_for_sf_type(parent_sf_type)
        child_sf_types = self._get_all_children_of_sf_type(parent_sf_type)

        query = f"SELECT {', '.join(parent_fields)}"
        for child_object_dict in child_sf_types:
            fields = self._get_all_fields_for_sf_type(child_object_dict["object_type"])
            query_addition = f", \n(SELECT {', '.join(fields)} FROM {child_object_dict['relationship_name']})"

            if len(query_addition) + len(query) > MAX_QUERY_LENGTH:
                query += f"\n FROM {parent_sf_type}"
                yield query
                query = "SELECT Id" + query_addition
            else:
                query += query_addition

        query += f"\n FROM {parent_sf_type}"

        yield query

    def _fetch_from_salesforce(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        time_filter_query = _build_time_filter_for_salesforce(start, end)

        doc_batch: list[Document] = []
        for parent_object_type in self.parent_object_list:
            logger.debug(f"Processing: {parent_object_type}")

            # This contains the dictionaries describing the top level
            # objects with the object id as the key
            query_results: dict[str, dict] = {}
            # loop over all queries and build the query_results dictionary
            for query in self._generate_query_per_parent_type(parent_object_type):
                query_result = self.sf_client.query_all(query + time_filter_query)
                for record_dict in query_result["records"]:
                    query_results.setdefault(record_dict["Id"], {}).update(record_dict)

            logger.info(
                f"Number of {parent_object_type} Objects processed: {len(query_results)}"
            )

            # loop over all the top level object dictionaries and convert them to documents
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
        return self._fetch_from_salesforce(start=start, end=end)

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateSlimDocumentOutput:
        doc_metadata_list: list[SlimDocument] = []
        for parent_object_type in self.parent_object_list:
            query = f"SELECT Id FROM {parent_object_type}"
            query_result = self.sf_client.query_all(query)
            doc_metadata_list.extend(
                SlimDocument(
                    id=f"{ID_PREFIX}{instance_dict.get('Id', '')}",
                    perm_sync_data={},
                )
                for instance_dict in query_result["records"]
            )

        yield doc_metadata_list


if __name__ == "__main__":
    connector = SalesforceConnector(
        requested_objects=os.environ["REQUESTED_OBJECTS"].split(",")
    )

    connector.load_credentials(
        {
            "sf_username": os.environ["SF_USERNAME"],
            "sf_password": os.environ["SF_PASSWORD"],
            "sf_security_token": os.environ["SF_SECURITY_TOKEN"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
