import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from pytz import UTC
from simple_salesforce import Salesforce
from simple_salesforce import SFType
from simple_salesforce.bulk2 import SFBulk2Handler
from simple_salesforce.bulk2 import SFBulk2Type

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.salesforce.sqlite_functions import has_at_least_one_object_of_type
from onyx.connectors.salesforce.utils import get_object_type_path
from onyx.utils.logger import setup_logger

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


def _get_sf_type_object_json(sf_client: Salesforce, type_name: str) -> Any:
    sf_object = SFType(type_name, sf_client.session_id, sf_client.sf_instance)
    return sf_object.describe()


def _is_valid_child_object(
    sf_client: Salesforce, child_relationship: dict[str, Any]
) -> bool:
    if not child_relationship["childSObject"]:
        return False
    if not child_relationship["relationshipName"]:
        return False

    sf_type = child_relationship["childSObject"]
    object_description = _get_sf_type_object_json(sf_client, sf_type)
    if not object_description["queryable"]:
        return False

    if child_relationship["field"]:
        if child_relationship["field"] == "RelatedToId":
            return False
    else:
        return False

    return True


def get_all_children_of_sf_type(sf_client: Salesforce, sf_type: str) -> set[str]:
    object_description = _get_sf_type_object_json(sf_client, sf_type)

    child_object_types = set()
    for child_relationship in object_description["childRelationships"]:
        if _is_valid_child_object(sf_client, child_relationship):
            logger.debug(
                f"Found valid child object {child_relationship['childSObject']}"
            )
            child_object_types.add(child_relationship["childSObject"])
    return child_object_types


def _get_all_queryable_fields_of_sf_type(
    sf_client: Salesforce,
    sf_type: str,
) -> list[str]:
    object_description = _get_sf_type_object_json(sf_client, sf_type)
    fields: list[dict[str, Any]] = object_description["fields"]
    valid_fields: set[str] = set()
    field_names_to_remove: set[str] = set()
    for field in fields:
        if compound_field_name := field.get("compoundFieldName"):
            # We do want to get name fields even if they are compound
            if not field.get("nameField"):
                field_names_to_remove.add(compound_field_name)
        if field.get("type", "base64") == "base64":
            continue
        if field_name := field.get("name"):
            valid_fields.add(field_name)

    return list(valid_fields - field_names_to_remove)


def _check_if_object_type_is_empty(
    sf_client: Salesforce, sf_type: str, time_filter: str
) -> bool:
    """
    Use the rest api to check to make sure the query will result in a non-empty response
    """
    try:
        query = f"SELECT Count() FROM {sf_type}{time_filter} LIMIT 1"
        result = sf_client.query(query)
        if result["totalSize"] == 0:
            return False
    except Exception as e:
        if "OPERATION_TOO_LARGE" not in str(e):
            logger.warning(f"Object type {sf_type} doesn't support query: {e}")
            return False
    return True


def _check_for_existing_csvs(sf_type: str) -> list[str] | None:
    # Check if the csv already exists
    if os.path.exists(get_object_type_path(sf_type)):
        existing_csvs = [
            os.path.join(get_object_type_path(sf_type), f)
            for f in os.listdir(get_object_type_path(sf_type))
            if f.endswith(".csv")
        ]
        # If the csv already exists, return the path
        # This is likely due to a previous run that failed
        # after downloading the csv but before the data was
        # written to the db
        if existing_csvs:
            return existing_csvs
    return None


def _build_bulk_query(sf_client: Salesforce, sf_type: str, time_filter: str) -> str:
    queryable_fields = _get_all_queryable_fields_of_sf_type(sf_client, sf_type)
    query = f"SELECT {', '.join(queryable_fields)} FROM {sf_type}{time_filter}"
    return query


def _bulk_retrieve_from_salesforce(
    sf_client: Salesforce,
    sf_type: str,
    time_filter: str,
) -> tuple[str, list[str] | None]:
    if not _check_if_object_type_is_empty(sf_client, sf_type, time_filter):
        return sf_type, None

    if existing_csvs := _check_for_existing_csvs(sf_type):
        return sf_type, existing_csvs

    query = _build_bulk_query(sf_client, sf_type, time_filter)

    bulk_2_handler = SFBulk2Handler(
        session_id=sf_client.session_id,
        bulk2_url=sf_client.bulk2_url,
        proxies=sf_client.proxies,
        session=sf_client.session,
    )
    bulk_2_type = SFBulk2Type(
        object_name=sf_type,
        bulk2_url=bulk_2_handler.bulk2_url,
        headers=bulk_2_handler.headers,
        session=bulk_2_handler.session,
    )

    logger.info(f"Downloading {sf_type}")
    logger.info(f"Query: {query}")

    try:
        # This downloads the file to a file in the target path with a random name
        results = bulk_2_type.download(
            query=query,
            path=get_object_type_path(sf_type),
            max_records=1000000,
        )
        all_download_paths = [result["file"] for result in results]
        logger.info(f"Downloaded {sf_type} to {all_download_paths}")
        return sf_type, all_download_paths
    except Exception as e:
        logger.info(f"Failed to download salesforce csv for object type {sf_type}: {e}")
        return sf_type, None


def fetch_all_csvs_in_parallel(
    sf_client: Salesforce,
    object_types: set[str],
    start: SecondsSinceUnixEpoch | None,
    end: SecondsSinceUnixEpoch | None,
) -> dict[str, list[str] | None]:
    """
    Fetches all the csvs in parallel for the given object types
    Returns a dict of (sf_type, full_download_path)
    """
    time_filter = _build_time_filter_for_salesforce(start, end)
    time_filter_for_each_object_type = {}
    # We do this outside of the thread pool executor because this requires
    # a database connection and we don't want to block the thread pool
    # executor from running
    for sf_type in object_types:
        """Only add time filter if there is at least one object of the type
        in the database. We aren't worried about partially completed object update runs
        because this occurs after we check for existing csvs which covers this case"""
        if has_at_least_one_object_of_type(sf_type):
            time_filter_for_each_object_type[sf_type] = time_filter
        else:
            time_filter_for_each_object_type[sf_type] = ""

    # Run the bulk retrieve in parallel
    with ThreadPoolExecutor() as executor:
        results = executor.map(
            lambda object_type: _bulk_retrieve_from_salesforce(
                sf_client=sf_client,
                sf_type=object_type,
                time_filter=time_filter_for_each_object_type[object_type],
            ),
            object_types,
        )
        return dict(results)
