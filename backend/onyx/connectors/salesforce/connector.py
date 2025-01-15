import os
from typing import Any

from simple_salesforce import Salesforce

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.salesforce.doc_conversion import convert_sf_object_to_doc
from onyx.connectors.salesforce.doc_conversion import ID_PREFIX
from onyx.connectors.salesforce.salesforce_calls import fetch_all_csvs_in_parallel
from onyx.connectors.salesforce.salesforce_calls import get_all_children_of_sf_type
from onyx.connectors.salesforce.sqlite_functions import get_affected_parent_ids_by_type
from onyx.connectors.salesforce.sqlite_functions import get_record
from onyx.connectors.salesforce.sqlite_functions import init_db
from onyx.connectors.salesforce.sqlite_functions import update_sf_db_with_csv
from onyx.utils.logger import setup_logger

logger = setup_logger()


_DEFAULT_PARENT_OBJECT_TYPES = ["Account"]


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
            else _DEFAULT_PARENT_OBJECT_TYPES
        )

    def load_credentials(
        self,
        credentials: dict[str, Any],
    ) -> dict[str, Any] | None:
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

    def _fetch_from_salesforce(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        init_db()
        all_object_types: set[str] = set(self.parent_object_list)

        logger.info(f"Starting with {len(self.parent_object_list)} parent object types")
        logger.debug(f"Parent object types: {self.parent_object_list}")

        # This takes like 20 seconds
        for parent_object_type in self.parent_object_list:
            child_types = get_all_children_of_sf_type(
                self.sf_client, parent_object_type
            )
            all_object_types.update(child_types)
            logger.debug(
                f"Found {len(child_types)} child types for {parent_object_type}"
            )

        # Always want to make sure user is grabbed for permissioning purposes
        all_object_types.add("User")

        logger.info(f"Found total of {len(all_object_types)} object types to fetch")
        logger.debug(f"All object types: {all_object_types}")

        # checkpoint - we've found all object types, now time to fetch the data
        logger.info("Starting to fetch CSVs for all object types")
        # This takes like 30 minutes first time and <2 minutes for updates
        object_type_to_csv_path = fetch_all_csvs_in_parallel(
            sf_client=self.sf_client,
            object_types=all_object_types,
            start=start,
            end=end,
        )

        updated_ids: set[str] = set()
        # This takes like 10 seconds
        # This is for testing the rest of the functionality if data has
        # already been fetched and put in sqlite
        # from import onyx.connectors.salesforce.sf_db.sqlite_functions find_ids_by_type
        # for object_type in self.parent_object_list:
        #     updated_ids.update(list(find_ids_by_type(object_type)))

        # This takes 10-70 minutes first time (idk why the range is so big)
        total_types = len(object_type_to_csv_path)
        logger.info(f"Starting to process {total_types} object types")

        for i, (object_type, csv_paths) in enumerate(
            object_type_to_csv_path.items(), 1
        ):
            logger.info(f"Processing object type {object_type} ({i}/{total_types})")
            # If path is None, it means it failed to fetch the csv
            if csv_paths is None:
                continue
            # Go through each csv path and use it to update the db
            for csv_path in csv_paths:
                logger.debug(f"Updating {object_type} with {csv_path}")
                new_ids = update_sf_db_with_csv(
                    object_type=object_type,
                    csv_download_path=csv_path,
                )
                updated_ids.update(new_ids)
                logger.debug(
                    f"Added {len(new_ids)} new/updated records for {object_type}"
                )

        logger.info(f"Found {len(updated_ids)} total updated records")
        logger.info(
            f"Starting to process parent objects of types: {self.parent_object_list}"
        )

        docs_to_yield: list[Document] = []
        docs_processed = 0
        # Takes 15-20 seconds per batch
        for parent_type, parent_id_batch in get_affected_parent_ids_by_type(
            updated_ids=list(updated_ids),
            parent_types=self.parent_object_list,
        ):
            logger.info(
                f"Processing batch of {len(parent_id_batch)} {parent_type} objects"
            )
            for parent_id in parent_id_batch:
                if not (parent_object := get_record(parent_id, parent_type)):
                    logger.warning(
                        f"Failed to get parent object {parent_id} for {parent_type}"
                    )
                    continue

                docs_to_yield.append(
                    convert_sf_object_to_doc(
                        sf_object=parent_object,
                        sf_instance=self.sf_client.sf_instance,
                    )
                )
                docs_processed += 1

                if len(docs_to_yield) >= self.batch_size:
                    yield docs_to_yield
                    docs_to_yield = []

        yield docs_to_yield

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
    import time

    connector = SalesforceConnector(requested_objects=["Account"])

    connector.load_credentials(
        {
            "sf_username": os.environ["SF_USERNAME"],
            "sf_password": os.environ["SF_PASSWORD"],
            "sf_security_token": os.environ["SF_SECURITY_TOKEN"],
        }
    )
    start_time = time.time()
    doc_count = 0
    section_count = 0
    text_count = 0
    for doc_batch in connector.load_from_state():
        doc_count += len(doc_batch)
        print(f"doc_count: {doc_count}")
        for doc in doc_batch:
            section_count += len(doc.sections)
            for section in doc.sections:
                text_count += len(section.text)
    end_time = time.time()

    print(f"Doc count: {doc_count}")
    print(f"Section count: {section_count}")
    print(f"Text count: {text_count}")
    print(f"Time taken: {end_time - start_time}")
