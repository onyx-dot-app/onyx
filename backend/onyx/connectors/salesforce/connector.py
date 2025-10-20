import csv
import gc
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from typing import cast

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.connectors.salesforce.doc_conversion import convert_sf_object_to_doc
from onyx.connectors.salesforce.doc_conversion import convert_sf_query_result_to_doc
from onyx.connectors.salesforce.doc_conversion import ID_PREFIX
from onyx.connectors.salesforce.onyx_salesforce import OnyxSalesforce
from onyx.connectors.salesforce.salesforce_calls import fetch_all_csvs_in_parallel
from onyx.connectors.salesforce.sqlite_functions import OnyxSalesforceSQLite
from onyx.connectors.salesforce.utils import ACCOUNT_OBJECT_TYPE
from onyx.connectors.salesforce.utils import BASE_DATA_PATH
from onyx.connectors.salesforce.utils import get_sqlite_db_path
from onyx.connectors.salesforce.utils import ID_FIELD
from onyx.connectors.salesforce.utils import MODIFIED_FIELD
from onyx.connectors.salesforce.utils import NAME_FIELD
from onyx.connectors.salesforce.utils import USER_OBJECT_TYPE
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT


logger = setup_logger()


_DEFAULT_PARENT_OBJECT_TYPES = [ACCOUNT_OBJECT_TYPE]

_DEFAULT_ATTRIBUTES_TO_KEEP: dict[str, dict[str, str]] = {
    "Opportunity": {
        ACCOUNT_OBJECT_TYPE: "account",
        "FiscalQuarter": "fiscal_quarter",
        "FiscalYear": "fiscal_year",
        "IsClosed": "is_closed",
        NAME_FIELD: "name",
        "StageName": "stage_name",
        "Type": "type",
        "Amount": "amount",
        "CloseDate": "close_date",
        "Probability": "probability",
        "CreatedDate": "created_date",
        MODIFIED_FIELD: "last_modified_date",
    },
    "Contact": {
        ACCOUNT_OBJECT_TYPE: "account",
        "CreatedDate": "created_date",
        MODIFIED_FIELD: "last_modified_date",
    },
}


class SalesforceCheckpoint(ConnectorCheckpoint):
    initial_sync_complete: bool
    current_timestamp: SecondsSinceUnixEpoch


class SalesforceConnectorContext:
    parent_types: set[str] = set()
    child_types: set[str] = set()
    parent_to_child_types: dict[str, set[str]] = {}  # map from parent to child types
    child_to_parent_types: dict[str, set[str]] = {}  # map from child to parent types
    parent_reference_fields_by_type: dict[str, dict[str, list[str]]] = {}
    type_to_queryable_fields: dict[str, set[str]] = {}
    prefix_to_type: dict[str, str] = {}  # infer the object type of an id immediately

    parent_to_child_relationships: dict[str, set[str]] = (
        {}
    )  # map from parent to child relationships
    parent_to_relationship_queryable_fields: dict[str, dict[str, set[str]]] = (
        {}
    )  # map from relationship to queryable fields

    parent_child_names_to_relationships: dict[str, str] = {}


def _extract_fields_and_associations_from_config(
    config: dict[str, Any], object_type: str
) -> tuple[list[str] | None, dict[str, list[str]]]:
    """
    Extract fields and associations for a specific object type from custom config.

    Returns:
        tuple of (fields_list, associations_dict)
        - fields_list: List of fields to query, or None if not specified (use all)
        - associations_dict: Dict mapping association names to their config
    """
    if object_type not in config:
        return None, {}

    obj_config = config[object_type]
    fields = obj_config.get("fields")
    associations = obj_config.get("associations", {})

    return fields, associations


def _validate_custom_query_config(config: dict[str, Any]) -> None:
    """
    Validate the structure of the custom query configuration.
    """

    for object_type, obj_config in config.items():
        if not isinstance(obj_config, dict):
            raise ValueError(
                f"top level object {object_type} must be mapped to a dictionary"
            )

        # Check if fields is a list when present
        if "fields" in obj_config:
            if not isinstance(obj_config["fields"], list):
                raise ValueError("if fields key exists, value must be a list")
            for v in obj_config["fields"]:
                if not isinstance(v, str):
                    raise ValueError(f"if fields list value {v} is not a string")

        # Check if associations is a dict when present
        if "associations" in obj_config:
            if not isinstance(obj_config["associations"], dict):
                raise ValueError(
                    "if associations key exists, value must be a dictionary"
                )
            for assoc_name, assoc_fields in obj_config["associations"].items():
                if not isinstance(assoc_fields, list):
                    raise ValueError(
                        f"associations list value {assoc_fields} for key {assoc_name} is not a list"
                    )
                for v in assoc_fields:
                    if not isinstance(v, str):
                        raise ValueError(
                            f"if associations list value {v} is not a string"
                        )


class SalesforceConnector(LoadConnector, PollConnector, SlimConnectorWithPermSync):
    """Approach outline

    Goal
    - get data for every record of every parent object type
    - The data should consist of the parent object record and all direct child relationship objects


    Initial sync
    - Does a full sync, then indexes each parent object + children as a document via
    the local sqlite db

    - get the first level children object types of parent object types
    - bulk export all object types to CSV
    -- NOTE: bulk exports of an object type contain parent id's, but not child id's
    - Load all CSV's to the DB
    - generate all parent object types as documents and yield them

    - Initial sync's must always be for the entire dataset.
      Otherwise, you can have cases where some records relate to other records that were
      updated recently. The more recently updated records will not be pulled down in the query.

    Delta sync's
    - delta sync's detect changes in parent objects, then perform a full sync of
    each parent object and its children

    If loading the entire db, this approach is much slower. For deltas, it works well.

    - query all changed records (includes children and parents)
    - extrapolate all changed parent objects
    - for each parent object, construct a query and yield the result back

    - Delta sync's can be done object by object by identifying the parent id of any changed
      record, and querying a single record at a time to get all the updated data.  In this way,
      we avoid having to keep a locally synchronized copy of the entire salesforce db.

    TODO: verify record to doc conversion
    figure out why sometimes the field names are missing.
    """

    MAX_BATCH_BYTES = 1024 * 1024
    LOG_INTERVAL = 10.0  # how often to log stats in loop heavy parts of the connector

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        requested_objects: list[str] = [],
        custom_query_config: str | None = None,
    ) -> None:
        self.batch_size = batch_size
        self._sf_client: OnyxSalesforce | None = None

        # Validate and store custom query config
        if custom_query_config:
            config_json = json.loads(custom_query_config)
            self.custom_query_config: dict[str, Any] | None = config_json
            # If custom query config is provided, use the object types from it
            self.parent_object_list = list(config_json.keys())
        else:
            self.custom_query_config = None
            # Use the traditional requested_objects approach
            self.parent_object_list = (
                [obj.strip().capitalize() for obj in requested_objects]
                if requested_objects
                else _DEFAULT_PARENT_OBJECT_TYPES
            )

    def load_credentials(
        self,
        credentials: dict[str, Any],
    ) -> dict[str, Any] | None:
        domain = "test" if credentials.get("is_sandbox") else None
        self._sf_client = OnyxSalesforce(
            username=credentials["sf_username"],
            password=credentials["sf_password"],
            security_token=credentials["sf_security_token"],
            domain=domain,
        )
        return None

    @property
    def sf_client(self) -> OnyxSalesforce:
        if self._sf_client is None:
            raise ConnectorMissingCredentialError("Salesforce")
        return self._sf_client

    @staticmethod
    def reconstruct_object_types(directory: str) -> dict[str, list[str] | None]:
        """
        Scans the given directory for all CSV files and reconstructs the available object types.
        Assumes filenames are formatted as "ObjectType.filename.csv" or "ObjectType.csv".

        Args:
            directory (str): The path to the directory containing CSV files.

        Returns:
            dict[str, list[str]]: A dictionary mapping object types to lists of file paths.
        """
        object_types = defaultdict(list)

        for filename in os.listdir(directory):
            if filename.endswith(".csv"):
                parts = filename.split(".", 1)  # Split on the first period
                object_type = parts[0]  # Take the first part as the object type
                object_types[object_type].append(os.path.join(directory, filename))

        return dict(object_types)

    @staticmethod
    def _download_object_csvs(
        all_types_to_filter: dict[str, bool],
        queryable_fields_by_type: dict[str, set[str]],
        directory: str,
        sf_client: OnyxSalesforce,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> None:
        # checkpoint - we've found all object types, now time to fetch the data
        logger.info("Fetching CSVs for all object types")

        # This takes like 30 minutes first time and <2 minutes for updates
        object_type_to_csv_path = fetch_all_csvs_in_parallel(
            sf_client=sf_client,
            all_types_to_filter=all_types_to_filter,
            queryable_fields_by_type=queryable_fields_by_type,
            start=start,
            end=end,
            target_dir=directory,
        )

        # print useful information
        num_csvs = 0
        num_bytes = 0
        for object_type, csv_paths in object_type_to_csv_path.items():
            if not csv_paths:
                continue

            for csv_path in csv_paths:
                if not csv_path:
                    continue

                file_path = Path(csv_path)
                file_size = file_path.stat().st_size
                num_csvs += 1
                num_bytes += file_size
                logger.info(
                    f"CSV download: object_type={object_type} path={csv_path} bytes={file_size}"
                )

        logger.info(
            f"CSV download total: total_csvs={num_csvs} total_bytes={num_bytes}"
        )

    @staticmethod
    def _load_csvs_to_db(
        csv_directory: str, remove_ids: bool, sf_db: OnyxSalesforceSQLite
    ) -> dict[str, str]:
        """
        Returns a dict of id to object type. Each id is a newly seen row in salesforce.
        """

        updated_ids: dict[str, str] = {}

        object_type_to_csv_path = SalesforceConnector.reconstruct_object_types(
            csv_directory
        )

        # NOTE(rkuo): this timing note is meaningless without a reference point in terms
        # of number of records, etc
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
                num_records = 0

                logger.debug(
                    f"Processing CSV: object_type={object_type} "
                    f"csv={csv_path} "
                    f"len={Path(csv_path).stat().st_size} "
                    f"records={num_records}"
                )

                with open(csv_path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        num_records += 1

                new_ids = sf_db.update_from_csv(
                    object_type=object_type,
                    csv_download_path=csv_path,
                    remove_ids=remove_ids,
                )
                for new_id in new_ids:
                    updated_ids[new_id] = object_type

                sf_db.flush()

                logger.debug(
                    f"Added {len(new_ids)} new/updated records for {object_type}"
                )

                logger.info(
                    f"Processed CSV: object_type={object_type} "
                    f"csv={csv_path} "
                    f"len={Path(csv_path).stat().st_size} "
                    f"records={num_records} "
                    f"db_len={sf_db.file_size}"
                )
                os.remove(csv_path)

        return updated_ids

    # @staticmethod
    # def _get_child_types(
    #     parent_types: list[str], sf_client: OnyxSalesforce
    # ) -> set[str]:
    #     all_types: set[str] = set(parent_types)

    #     # Step 1 - get all object types
    #     logger.info(f"Parent object types: num={len(parent_types)} list={parent_types}")

    #     # This takes like 20 seconds
    #     for parent_object_type in parent_types:
    #         child_types = sf_client.get_children_of_sf_type(parent_object_type)
    #         logger.debug(
    #             f"Found {len(child_types)} child types for {parent_object_type}"
    #         )

    #         all_types.update(child_types.keys())

    #     # Always want to make sure user is grabbed for permissioning purposes
    #     all_types.add(USER_OBJECT_TYPE)
    #     # Always want to make sure account is grabbed for reference purposes
    #     all_types.add(ACCOUNT_OBJECT_TYPE)

    #     logger.info(f"All object types: num={len(all_types)} list={all_types}")

    #     # gc.collect()
    #     return all_types

    # @staticmethod
    # def _get_all_types(parent_types: list[str], sf_client: Salesforce) -> set[str]:
    #     all_types: set[str] = set(parent_types)

    #     # Step 1 - get all object types
    #     logger.info(f"Parent object types: num={len(parent_types)} list={parent_types}")

    #     # This takes like 20 seconds
    #     for parent_object_type in parent_types:
    #         child_types = get_children_of_sf_type(sf_client, parent_object_type)
    #         logger.debug(
    #             f"Found {len(child_types)} child types for {parent_object_type}"
    #         )

    #         all_types.update(child_types)

    #     # Always want to make sure user is grabbed for permissioning purposes
    #     all_types.add(USER_OBJECT_TYPE)

    #     logger.info(f"All object types: num={len(all_types)} list={all_types}")

    #     # gc.collect()
    #     return all_types

    def _full_sync(
        self,
        temp_dir: str,
    ) -> GenerateDocumentsOutput:
        type_to_processed: dict[str, int] = {}

        logger.info("_fetch_from_salesforce starting (full sync).")
        if not self._sf_client:
            raise RuntimeError("self._sf_client is None!")

        docs_to_yield: list[Document] = []

        changed_ids_to_type: dict[str, str] = {}
        parents_changed = 0
        examined_ids = 0

        sf_db = OnyxSalesforceSQLite(os.path.join(temp_dir, "salesforce_db.sqlite"))
        sf_db.connect()

        try:
            sf_db.apply_schema()
            sf_db.log_stats()

            ctx = self._make_context(
                None, None, temp_dir, self.parent_object_list, self._sf_client
            )
            gc.collect()

            # Step 2 - load CSV's to sqlite
            object_type_to_csv_paths = SalesforceConnector.reconstruct_object_types(
                temp_dir
            )

            total_types = len(object_type_to_csv_paths)
            logger.info(f"Starting to process {total_types} object types")

            for i, (object_type, csv_paths) in enumerate(
                object_type_to_csv_paths.items(), 1
            ):
                logger.info(f"Processing object type {object_type} ({i}/{total_types})")
                # If path is None, it means it failed to fetch the csv
                if csv_paths is None:
                    continue

                # Go through each csv path and use it to update the db
                for csv_path in csv_paths:
                    num_records = 0
                    with open(csv_path, "r", newline="", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            num_records += 1

                    logger.debug(
                        f"Processing CSV: object_type={object_type} "
                        f"csv={csv_path} "
                        f"len={Path(csv_path).stat().st_size} "
                        f"records={num_records}"
                    )

                    # yield an empty list to keep the connector alive
                    yield docs_to_yield

                    new_ids = sf_db.update_from_csv(
                        object_type=object_type,
                        csv_download_path=csv_path,
                    )
                    for new_id in new_ids:
                        changed_ids_to_type[new_id] = object_type

                    sf_db.flush()

                    logger.debug(
                        f"Added {len(new_ids)} new/updated records for {object_type}"
                    )

                    logger.info(
                        f"Processed CSV: object_type={object_type} "
                        f"csv={csv_path} "
                        f"len={Path(csv_path).stat().st_size} "
                        f"records={num_records} "
                        f"db_len={sf_db.file_size}"
                    )

                    os.remove(csv_path)
                    gc.collect()

            gc.collect()

            logger.info(f"Found {len(changed_ids_to_type)} total updated records")
            logger.info(
                f"Starting to process parent objects of types: {ctx.parent_types}"
            )

            # Step 3 - extract and index docs
            docs_to_yield_bytes = 0

            last_log_time = 0.0

            for (
                parent_type,
                parent_id,
                examined_ids,
            ) in sf_db.get_changed_parent_ids_by_type(
                changed_ids=list(changed_ids_to_type.keys()),
                parent_types=ctx.parent_types,
            ):
                now = time.monotonic()

                processed = examined_ids - 1
                if now - last_log_time > SalesforceConnector.LOG_INTERVAL:
                    logger.info(
                        f"Processing stats: {type_to_processed} "
                        f"file_size={sf_db.file_size} "
                        f"processed={processed} "
                        f"remaining={len(changed_ids_to_type) - processed}"
                    )
                    last_log_time = now

                type_to_processed[parent_type] = (
                    type_to_processed.get(parent_type, 0) + 1
                )

                parent_object = sf_db.get_record(parent_id, parent_type)
                if not parent_object:
                    logger.warning(
                        f"Failed to get parent object {parent_id} for {parent_type}"
                    )
                    continue

                # use the db to create a document we can yield
                doc = convert_sf_object_to_doc(
                    sf_db,
                    sf_object=parent_object,
                    sf_instance=self.sf_client.sf_instance,
                )

                doc.metadata["object_type"] = parent_type

                # Add default attributes to the metadata
                for (
                    sf_attribute,
                    canonical_attribute,
                ) in _DEFAULT_ATTRIBUTES_TO_KEEP.get(parent_type, {}).items():
                    if sf_attribute in parent_object.data:
                        doc.metadata[canonical_attribute] = parent_object.data[
                            sf_attribute
                        ]

                doc_sizeof = sys.getsizeof(doc)
                docs_to_yield_bytes += doc_sizeof
                docs_to_yield.append(doc)
                parents_changed += 1

                # memory usage is sensitive to the input length, so we're yielding immediately
                # if the batch exceeds a certain byte length
                if (
                    len(docs_to_yield) >= self.batch_size
                    or docs_to_yield_bytes > SalesforceConnector.MAX_BATCH_BYTES
                ):
                    yield docs_to_yield
                    docs_to_yield = []
                    docs_to_yield_bytes = 0

                    # observed a memory leak / size issue with the account table if we don't gc.collect here.
                    gc.collect()

            yield docs_to_yield
        except Exception:
            logger.exception("Unexpected exception")
            raise
        finally:
            logger.info(
                f"Final processing stats: "
                f"examined={examined_ids} "
                f"parents_changed={parents_changed} "
                f"remaining={len(changed_ids_to_type) - examined_ids}"
            )

            logger.info(f"Top level object types processed: {type_to_processed}")

            sf_db.close()

    def _delta_sync(
        self,
        temp_dir: str,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        type_to_processed: dict[str, int] = {}

        logger.info("_fetch_from_salesforce starting (delta sync).")
        if not self._sf_client:
            raise RuntimeError("self._sf_client is None!")

        changed_ids_to_type: dict[str, str] = {}
        parents_changed = 0
        processed = 0

        sf_db = OnyxSalesforceSQLite(os.path.join(temp_dir, "salesforce_db.sqlite"))
        sf_db.connect()

        try:
            sf_db.apply_schema()
            sf_db.log_stats()

            ctx = self._make_context(
                start, end, temp_dir, self.parent_object_list, self._sf_client
            )
            gc.collect()

            # Step 2 - load CSV's to sqlite
            changed_ids_to_type = SalesforceConnector._load_csvs_to_db(
                temp_dir, False, sf_db
            )
            gc.collect()

            logger.info(f"Found {len(changed_ids_to_type)} total updated records")
            logger.info(
                f"Starting to process parent objects of types: {ctx.parent_types}"
            )

            # Step 3 - extract and index docs
            docs_to_yield: list[Document] = []
            docs_to_yield_bytes = 0

            last_log_time = 0.0

            # this is a partial sync, so all changed parent id's must be retrieved from salesforce
            # NOTE: it may be an option to identify the object type of an id with its prefix
            # but unfortunately it's possible for an object type to not have a prefix.
            # so that would work in many important cases, but not all.
            for (
                parent_id,
                actual_parent_type,
                num_examined,
            ) in sf_db.get_changed_parent_ids_by_type_2(
                changed_ids=changed_ids_to_type,
                parent_types=ctx.parent_types,
                parent_relationship_fields_by_type=ctx.parent_reference_fields_by_type,
                prefix_to_type=ctx.prefix_to_type,
            ):
                # this yields back each changed parent record, where changed means
                # the parent record itself or a child record was updated.
                now = time.monotonic()

                # query salesforce for the changed parent id record
                # NOTE(rkuo): we only know the record id and its possible types,
                # so we actually need to check each type until we succeed
                # to be entirely correct
                # this may be a source of inefficiency and thinking about
                # caching the most likely parent record type might be helpful

                # actual_parent_type: str | None = None
                # for possible_parent_type in possible_parent_types:
                #     queryable_fields = ctx.queryable_fields_by_type[
                #         possible_parent_type
                #     ]
                #     query = _get_object_by_id_query(
                #         parent_id, possible_parent_type, queryable_fields
                #     )
                #     result = self._sf_client.query(query)
                #     if result:
                #         actual_parent_type = possible_parent_type
                #         print(result)
                #         break

                # get the parent record fields
                record = self._sf_client.query_object(
                    actual_parent_type, parent_id, ctx.type_to_queryable_fields
                )
                if not record:
                    continue

                # queryable_fields = ctx.type_to_queryable_fields[
                #     actual_parent_type
                # ]
                # query = get_object_by_id_query(
                #     parent_id, actual_parent_type, queryable_fields
                # )
                # result = self._sf_client.query(query)
                # if not result:
                #     continue

                # # print(result)
                # record: dict[str, Any] = {}

                # record_0 = result["records"][0]
                # for record_key, record_value in record_0.items():
                #     if record_key == "attributes":
                #         continue

                #     record[record_key] = record_value

                # for this parent type, increment the counter on the stats object
                type_to_processed[actual_parent_type] = (
                    type_to_processed.get(actual_parent_type, 0) + 1
                )

                # get the child records
                child_relationships = ctx.parent_to_child_relationships[
                    actual_parent_type
                ]
                relationship_to_queryable_fields = (
                    ctx.parent_to_relationship_queryable_fields[actual_parent_type]
                )
                child_records = self.sf_client.get_child_objects_by_id(
                    parent_id,
                    actual_parent_type,
                    list(child_relationships),
                    relationship_to_queryable_fields,
                )

                # NOTE(rkuo): does using the parent last modified make sense if the update
                # is being triggered because a child object changed?
                primary_owner_list: list[BasicExpertInfo] | None = None
                if "LastModifiedById" in record:
                    try:
                        last_modified_by_id = record["LastModifiedById"]
                        user_record = self.sf_client.query_object(
                            USER_OBJECT_TYPE,
                            last_modified_by_id,
                            ctx.type_to_queryable_fields,
                        )
                        if user_record:
                            primary_owner = BasicExpertInfo.from_dict(user_record)
                            primary_owner_list = [primary_owner]
                    except Exception:
                        pass

                # for child_record_key, child_record in child_records.items():
                #     if not child_record:
                #         continue

                #     child_text_section = _extract_section(
                #         child_record,
                #         f"https://{self._sf_client.sf_instance}/{child_record_key}",
                #     )
                #     sections.append(child_text_section)

                # for parent_relationship_field in parent_relationship_fields:
                #     parent_relationship_id
                # json.loads(parent_object.data)

                # create and yield a document from the salesforce query
                doc = convert_sf_query_result_to_doc(
                    parent_id,
                    record,
                    child_records,
                    primary_owner_list,
                    self._sf_client,
                )

                # doc = Document(
                #     id=ID_PREFIX + parent_id,
                #     sections=cast(list[TextSection | ImageSection], sections),
                #     source=DocumentSource.SALESFORCE,
                #     semantic_identifier=parent_semantic_identifier,
                #     doc_updated_at=time_str_to_utc(parent_last_modified_date),
                #     primary_owners=primary_owner_list,
                #     metadata={},
                # )

                # Add default attributes to the metadata
                for (
                    sf_attribute,
                    canonical_attribute,
                ) in _DEFAULT_ATTRIBUTES_TO_KEEP.get(actual_parent_type, {}).items():
                    if sf_attribute in record:
                        doc.metadata[canonical_attribute] = record[sf_attribute]

                doc_sizeof = sys.getsizeof(doc)
                docs_to_yield_bytes += doc_sizeof
                docs_to_yield.append(doc)
                parents_changed += 1

                # memory usage is sensitive to the input length, so we're yielding immediately
                # if the batch exceeds a certain byte length
                if (
                    len(docs_to_yield) >= self.batch_size
                    or docs_to_yield_bytes > SalesforceConnector.MAX_BATCH_BYTES
                ):
                    yield docs_to_yield
                    docs_to_yield = []
                    docs_to_yield_bytes = 0

                    # observed a memory leak / size issue with the account table if we don't gc.collect here.
                    gc.collect()

                processed = num_examined
                if now - last_log_time > SalesforceConnector.LOG_INTERVAL:
                    logger.info(
                        f"Processing stats: {type_to_processed} "
                        f"processed={processed} "
                        f"remaining={len(changed_ids_to_type) - processed}"
                    )
                    last_log_time = now

            yield docs_to_yield
        except Exception:
            logger.exception("Unexpected exception")
            raise
        finally:
            logger.info(
                f"Final processing stats: "
                f"processed={processed} "
                f"remaining={len(changed_ids_to_type) - processed} "
                f"parents_changed={parents_changed}"
            )

            logger.info(f"Top level object types processed: {type_to_processed}")

            sf_db.close()

    def _make_context(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        temp_dir: str,
        parent_object_list: list[str],
        sf_client: OnyxSalesforce,
    ) -> SalesforceConnectorContext:
        """NOTE: I suspect we're doing way too many queries here. Likely fewer queries
        and just parsing all the info we need in less passes will work."""

        parent_types = set(parent_object_list)
        child_types: set[str] = set()
        parent_to_child_types: dict[str, set[str]] = (
            {}
        )  # map from parent to child types
        child_to_parent_types: dict[str, set[str]] = (
            {}
        )  # map from child to parent types

        parent_reference_fields_by_type: dict[str, dict[str, list[str]]] = (
            {}
        )  # for a given object, the fields reference parent objects
        type_to_queryable_fields: dict[str, set[str]] = {}
        prefix_to_type: dict[str, str] = {}

        parent_to_child_relationships: dict[str, set[str]] = (
            {}
        )  # map from parent to child relationships

        # relationship keys are formatted as "parent__relationship"
        # we have to do this because relationship names are not unique!
        # values are a dict of relationship names to a list of queryable fields
        parent_to_relationship_queryable_fields: dict[str, dict[str, set[str]]] = {}

        parent_child_names_to_relationships: dict[str, str] = {}

        full_sync = start is None and end is None

        # Step 1 - make a list of all the types to download (parent + direct child + USER_OBJECT_TYPE)
        # prefixes = {}

        global_description = sf_client.describe()
        if not global_description:
            raise RuntimeError("sf_client.describe failed")

        for sobject in global_description["sobjects"]:
            if sobject["keyPrefix"]:
                prefix_to_type[sobject["keyPrefix"]] = sobject["name"]
                # prefixes[sobject['keyPrefix']] = {
                #     'object_name': sobject['name'],
                #     'label': sobject['label'],
                #     'is_custom': sobject['custom']
                # }

        logger.info(f"Describe: num_prefixes={len(prefix_to_type)}")

        logger.info(f"Parent object types: num={len(parent_types)} list={parent_types}")
        for parent_type in parent_types:
            # parent_onyx_sf_type = OnyxSalesforceType(parent_type, sf_client)

            custom_fields: list[str] | None = []
            associations_config: dict[str, list[str]] | None = None

            # Set queryable fields for parent type
            if self.custom_query_config:
                custom_fields, associations_config = (
                    _extract_fields_and_associations_from_config(
                        self.custom_query_config, parent_type
                    )
                )
                custom_fields = custom_fields or []

                # Get custom fields for parent type
                field_set = set(custom_fields)
                # used during doc conversion
                # field_set.add(NAME_FIELD) # does not always exist
                field_set.add(ID_FIELD)
                field_set.add(MODIFIED_FIELD)

                # Use only the specified fields
                type_to_queryable_fields[parent_type] = field_set
                logger.info(f"Using custom fields for {parent_type}: {field_set}")
            else:
                # Use all queryable fields
                type_to_queryable_fields[parent_type] = (
                    sf_client.get_queryable_fields_by_type(parent_type)
                )
                logger.info(f"Using all fields for {parent_type}")

            child_types_all = sf_client.get_children_of_sf_type(parent_type)
            logger.debug(f"Found {len(child_types_all)} child types for {parent_type}")
            logger.debug(f"child types: {child_types_all}")

            child_types_working = child_types_all.copy()
            if associations_config is not None:
                child_types_working = {
                    k: v for k, v in child_types_all.items() if k in associations_config
                }
                any_not_found = False
                for k in associations_config:
                    if k not in child_types_working:
                        any_not_found = True
                        logger.warning(f"Association {k} not found in {parent_type}")
                if any_not_found:
                    queryable_fields = sf_client.get_queryable_fields_by_type(
                        parent_type
                    )
                    raise RuntimeError(
                        f"Associations {associations_config} not found in {parent_type} "
                        "make sure your parent-child associations are in the right order"
                        # f"with child objects {child_types_all}"
                        # f" and fields {queryable_fields}"
                    )

            parent_to_child_relationships[parent_type] = set()
            parent_to_child_types[parent_type] = set()
            parent_to_relationship_queryable_fields[parent_type] = {}

            for child_type, child_relationship in child_types_working.items():
                child_type = cast(str, child_type)

                # onyx_sf_type = OnyxSalesforceType(child_type, sf_client)

                # map parent name to child name
                parent_to_child_types[parent_type].add(child_type)

                # reverse map child name to parent name
                if child_type not in child_to_parent_types:
                    child_to_parent_types[child_type] = set()
                child_to_parent_types[child_type].add(parent_type)

                # map parent name to child relationship
                parent_to_child_relationships[parent_type].add(child_relationship)

                # map relationship to queryable fields of the target table
                if config_fields := (
                    associations_config and associations_config.get(child_type)
                ):
                    field_set = set(config_fields)
                    # these are expected and used during doc conversion
                    # field_set.add(NAME_FIELD) # does not always exist
                    field_set.add(ID_FIELD)
                    field_set.add(MODIFIED_FIELD)
                    queryable_fields = field_set
                else:
                    queryable_fields = sf_client.get_queryable_fields_by_type(
                        child_type
                    )

                if child_relationship in parent_to_relationship_queryable_fields:
                    raise RuntimeError(f"{child_relationship=} already exists")

                parent_to_relationship_queryable_fields[parent_type][
                    child_relationship
                ] = queryable_fields

                type_to_queryable_fields[child_type] = queryable_fields

                parent_child_names_to_relationships[f"{parent_type}__{child_type}"] = (
                    child_relationship
                )

            child_types.update(child_types_working.keys())
            logger.info(
                f"Child object types: parent={parent_type} num={len(child_types_working)} list={child_types_working.keys()}"
            )

        logger.info(
            f"Final child object types: num={len(child_types)} list={child_types}"
        )

        all_types: set[str] = set(parent_types)
        all_types.update(child_types)

        # NOTE(rkuo): should this be an implicit parent type?
        all_types.add(USER_OBJECT_TYPE)  # Always add User for permissioning purposes
        all_types.add(ACCOUNT_OBJECT_TYPE)  # Always add Account for reference purposes

        logger.info(f"All object types: num={len(all_types)} list={all_types}")

        # Ensure User and Account have queryable fields if they weren't already processed
        essential_types = [USER_OBJECT_TYPE, ACCOUNT_OBJECT_TYPE]
        for essential_type in essential_types:
            if essential_type not in type_to_queryable_fields:
                type_to_queryable_fields[essential_type] = (
                    sf_client.get_queryable_fields_by_type(essential_type)
                )

        # 1.1 - Detect all fields in child types which reference a parent type.
        # build dicts to detect relationships between parent and child
        for child_type in child_types.union(essential_types):
            # onyx_sf_type = OnyxSalesforceType(child_type, sf_client)
            parent_reference_fields = sf_client.get_parent_reference_fields(
                child_type, parent_types
            )

            parent_reference_fields_by_type[child_type] = parent_reference_fields

        # Only add time filter if there is at least one object of the type
        # in the database. We aren't worried about partially completed object update runs
        # because this occurs after we check for existing csvs which covers this case
        # NOTE(rkuo):
        all_types_to_filter: dict[str, bool] = {}
        for sf_type in all_types:
            # onyx_sf_type = OnyxSalesforceType(sf_type, sf_client)

            # NOTE(rkuo): I'm not convinced it makes sense to restrict filtering at all
            # all_types_to_filter[sf_type] = sf_db.object_type_count(sf_type) > 0
            all_types_to_filter[sf_type] = not full_sync

        # Step 1.2 - bulk download the CSV's for each object type
        SalesforceConnector._download_object_csvs(
            all_types_to_filter,
            type_to_queryable_fields,
            temp_dir,
            sf_client,
            start,
            end,
        )

        return_context = SalesforceConnectorContext()
        return_context.parent_types = parent_types
        return_context.child_types = child_types
        return_context.parent_to_child_types = parent_to_child_types
        return_context.child_to_parent_types = child_to_parent_types
        return_context.parent_reference_fields_by_type = parent_reference_fields_by_type
        return_context.type_to_queryable_fields = type_to_queryable_fields
        return_context.prefix_to_type = prefix_to_type

        return_context.parent_to_child_relationships = parent_to_child_relationships
        return_context.parent_to_relationship_queryable_fields = (
            parent_to_relationship_queryable_fields
        )

        return_context.parent_child_names_to_relationships = (
            parent_child_names_to_relationships
        )

        return return_context

    def load_from_state(self) -> GenerateDocumentsOutput:
        if MULTI_TENANT:
            # if multi tenant, we cannot expect the sqlite db to be cached/present
            with tempfile.TemporaryDirectory() as temp_dir:
                return self._full_sync(temp_dir)

        # nuke the db since we're starting from scratch
        sqlite_db_path = get_sqlite_db_path(BASE_DATA_PATH)
        if os.path.exists(sqlite_db_path):
            logger.info(f"load_from_state: Removing db at {sqlite_db_path}.")
            os.remove(sqlite_db_path)
        return self._full_sync(BASE_DATA_PATH)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Poll source will synchronize updated parent objects one by one."""

        if start == 0:
            # nuke the db if we're starting from scratch
            sqlite_db_path = get_sqlite_db_path(BASE_DATA_PATH)
            if os.path.exists(sqlite_db_path):
                logger.info(
                    f"poll_source: Starting at time 0, removing db at {sqlite_db_path}."
                )
                os.remove(sqlite_db_path)

            return self._delta_sync(BASE_DATA_PATH, start, end)

        with tempfile.TemporaryDirectory() as temp_dir:
            return self._delta_sync(temp_dir, start, end)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        doc_metadata_list: list[SlimDocument] = []
        for parent_object_type in self.parent_object_list:
            query = f"SELECT Id FROM {parent_object_type}"
            query_result = self.sf_client.safe_query_all(query)
            doc_metadata_list.extend(
                SlimDocument(
                    id=f"{ID_PREFIX}{instance_dict.get('Id', '')}",
                    external_access=None,
                )
                for instance_dict in query_result["records"]
            )

        yield doc_metadata_list

    def validate_connector_settings(self) -> None:
        """
        Validate that the Salesforce credentials and connector settings are correct.
        Specifically checks that we can make an authenticated request to Salesforce.
        """

        try:
            # Attempt to fetch a small batch of objects (arbitrary endpoint) to verify credentials
            self.sf_client.describe()
        except Exception as e:
            raise ConnectorMissingCredentialError(
                "Failed to validate Salesforce credentials. Please check your"
                f"credentials and try again. Error: {e}"
            )

        if self.custom_query_config:
            try:
                _validate_custom_query_config(self.custom_query_config)
            except Exception as e:
                raise ConnectorMissingCredentialError(
                    "Failed to validate Salesforce custom query config. Please check your"
                    f"config and try again. Error: {e}"
                )

        logger.info("Salesforce credentials validated successfully.")

    # @override
    # def load_from_checkpoint(
    #     self,
    #     start: SecondsSinceUnixEpoch,
    #     end: SecondsSinceUnixEpoch,
    #     checkpoint: SalesforceCheckpoint,
    # ) -> CheckpointOutput[SalesforceCheckpoint]:
    #     try:
    #         return self._fetch_document_batches(checkpoint, start, end)
    #     except Exception as e:
    #         if _should_propagate_error(e) and start is not None:
    #             logger.warning(
    #                 "Confluence says we provided an invalid 'updated' field. This may indicate"
    #                 "a real issue, but can also appear during edge cases like daylight"
    #                 f"savings time changes. Retrying with a 1 hour offset. Error: {e}"
    #             )
    #             return self._fetch_document_batches(checkpoint, start - ONE_HOUR, end)
    #         raise

    # @override
    # def build_dummy_checkpoint(self) -> SalesforceCheckpoint:
    #     return SalesforceCheckpoint(last_updated=0, has_more=True, last_seen_doc_ids=[])

    # @override
    # def validate_checkpoint_json(self, checkpoint_json: str) -> SalesforceCheckpoint:
    #     return SalesforceCheckpoint.model_validate_json(checkpoint_json)


if __name__ == "__main__":
    connector = SalesforceConnector(requested_objects=[ACCOUNT_OBJECT_TYPE])

    connector.load_credentials(
        {
            "sf_username": os.environ["SF_USERNAME"],
            "sf_password": os.environ["SF_PASSWORD"],
            "sf_security_token": os.environ["SF_SECURITY_TOKEN"],
        }
    )
    start_time = time.monotonic()
    doc_count = 0
    section_count = 0
    text_count = 0
    for doc_batch in connector.load_from_state():
        doc_count += len(doc_batch)
        print(f"doc_count: {doc_count}")
        for doc in doc_batch:
            section_count += len(doc.sections)
            for section in doc.sections:
                if isinstance(section, TextSection) and section.text is not None:
                    text_count += len(section.text)
    end_time = time.monotonic()

    print(f"Doc count: {doc_count}")
    print(f"Section count: {section_count}")
    print(f"Text count: {text_count}")
    print(f"Time taken: {end_time - start_time}")
