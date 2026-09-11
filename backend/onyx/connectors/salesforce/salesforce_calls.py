from __future__ import annotations

import gc
import os
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import zip_longest
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from pytz import UTC
from simple_salesforce import Salesforce
from simple_salesforce.bulk2 import QueryResult, SFBulk2Handler, SFBulk2Type
from simple_salesforce.exceptions import (
    SalesforceExpiredSession,
    SalesforceRefusedRequest,
)
from simple_salesforce.format import format_soql

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rate_limit_builder
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.salesforce.utils import (
    CREATED_FIELD,
    ID_FIELD,
    MODIFIED_FIELD,
    validate_sf_identifier,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

if TYPE_CHECKING:
    from onyx.connectors.salesforce.onyx_salesforce import OnyxSalesforce

logger = setup_logger()

# Salesforce returns HTTP 431 once URI plus headers pass 16,384 bytes, and SOQL
# travels in the GET query string. Room is left for the base URL and headers.
SOQL_MAX_URL_ENCODED_LENGTH = 12_000
SOQL_SELECT_PREFIX = "SELECT "
SOQL_FIELD_SEPARATOR = ", "
# parent-to-child subqueries Salesforce accepts in one query
SOQL_MAX_SUBQUERIES = 20
# child rows per relationship, kept small to bound the parent document
SOQL_SUBQUERY_ROW_LIMIT = 10


def is_salesforce_rate_limit_error(exception: Exception) -> bool:
    """Check if an exception is a Salesforce rate limit error."""
    return isinstance(
        exception, SalesforceRefusedRequest
    ) and "REQUEST_LIMIT_EXCEEDED" in str(exception)


def _build_last_modified_time_filter_for_salesforce(
    start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
) -> str:
    if start is None or end is None:
        return ""
    start_datetime = datetime.fromtimestamp(start, UTC)
    end_datetime = datetime.fromtimestamp(end, UTC)
    return f" WHERE LastModifiedDate > {start_datetime.isoformat()} AND LastModifiedDate < {end_datetime.isoformat()}"


def _build_created_date_time_filter_for_salesforce(
    start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
) -> str:
    if start is None or end is None:
        return ""
    start_datetime = datetime.fromtimestamp(start, UTC)
    end_datetime = datetime.fromtimestamp(end, UTC)
    return f" WHERE CreatedDate > {start_datetime.isoformat()} AND CreatedDate < {end_datetime.isoformat()}"


def _make_time_filter_for_sf_type(
    queryable_fields: set[str],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> str | None:
    if MODIFIED_FIELD in queryable_fields:
        return _build_last_modified_time_filter_for_salesforce(start, end)

    if "CreatedDate" in queryable_fields:
        return _build_created_date_time_filter_for_salesforce(start, end)

    return None


def _make_time_filtered_query(
    queryable_fields: set[str], sf_type: str, time_filter: str
) -> str:
    # SOQL has no parameter binding for table/column identifiers, so the SF
    # type and field names are validated against a strict regex before being
    # interpolated. time_filter is built internally from datetime.isoformat().
    validate_sf_identifier(sf_type)
    fields = SOQL_FIELD_SEPARATOR.join(
        validate_sf_identifier(f) for f in queryable_fields
    )
    query = f"SELECT {fields} FROM {sf_type}{time_filter}"  # noqa: S608
    return query


def _url_encoded_length(text: str) -> int:
    # requests encodes the q= parameter with quote_plus
    return len(quote_plus(text))


def _pack_for_url(
    items: Iterable[str],
    separator: str,
    max_encoded_length: int,
    max_items: int | None = None,
) -> list[list[str]]:
    """Greedily group items so each group, joined by separator, fits the URL
    budget. A group is never empty, so an item that alone exceeds the budget
    still goes through and lets Salesforce report the problem."""
    separator_length = _url_encoded_length(separator)
    groups: list[list[str]] = []
    current: list[str] = []
    current_length = 0
    for item in items:
        item_length = _url_encoded_length(item)
        added_length = item_length + (separator_length if current else 0)
        too_long = current_length + added_length > max_encoded_length
        too_many = max_items is not None and len(current) >= max_items
        if current and (too_long or too_many):
            groups.append(current)
            current = []
            current_length = 0
            added_length = item_length
        current.append(item)
        current_length += added_length
    if current:
        groups.append(current)
    return groups


def _object_by_id_suffix(object_id: str, sf_type: str) -> str:
    """FROM/WHERE clause that follows a field list."""
    # SOQL has no parameter binding for identifiers, so sf_type is regex-validated.
    # object_id is an SF-issued record ID from an earlier SOQL response, but
    # we still quote-escape it via format_soql for safety.
    validate_sf_identifier(sf_type)
    return format_soql(
        f" FROM {sf_type} WHERE Id = {{object_id}}",  # noqa: S608
        object_id=object_id,
    )


def _field_budget(suffix: str) -> int:
    return SOQL_MAX_URL_ENCODED_LENGTH - _url_encoded_length(
        SOQL_SELECT_PREFIX + suffix
    )


def get_object_by_id_queries(
    object_id: str, sf_type: str, queryable_fields: set[str]
) -> list[str]:
    """SOQL queries that together select every field of one record.

    Each query fits the URL budget. The caller merges the results. Fields are
    sorted so a field set always produces the same queries."""
    suffix = _object_by_id_suffix(object_id, sf_type)
    fields = sorted(validate_sf_identifier(f) for f in queryable_fields)
    return [
        SOQL_SELECT_PREFIX + SOQL_FIELD_SEPARATOR.join(chunk) + suffix
        for chunk in _pack_for_url(fields, SOQL_FIELD_SEPARATOR, _field_budget(suffix))
    ]


def _child_order_by(queryable_fields: set[str]) -> str:
    # newest children first so a recently changed child makes the window, with
    # Id as tiebreaker so every field chunk of one relationship sees the same rows
    for field in (MODIFIED_FIELD, CREATED_FIELD):
        if field in queryable_fields:
            return f"ORDER BY {field} DESC, {ID_FIELD} DESC"
    return f"ORDER BY {ID_FIELD} DESC"


def _make_child_subquery(
    child_relationship: str, fields: list[str], order_by: str
) -> str:
    # NOTE: fields must be listed explicitly. These shortcuts don't work:
    #   FIELDS(ALL) can include binary fields, so don't use that
    #   FIELDS(CUSTOM) can include aggregate queries, so don't use that
    validate_sf_identifier(child_relationship)
    fields_fragment = SOQL_FIELD_SEPARATOR.join(
        validate_sf_identifier(f) for f in fields
    )
    return (
        f"(SELECT {fields_fragment} FROM {child_relationship} "  # noqa: S608
        f"{order_by} LIMIT {SOQL_SUBQUERY_ROW_LIMIT})"
    )


def get_child_objects_by_id_queries(
    object_id: str,
    sf_type: str,
    child_relationships: list[str],
    relationships_to_fields: dict[str, set[str]],
) -> list[str]:
    """SOQL queries whose subqueries together fetch every child relationship.

    Each query fits the URL budget and the subquery cap and names a relationship
    at most once, so the caller can merge field chunks of a relationship by Id."""
    suffix = _object_by_id_suffix(object_id, sf_type)
    budget = _field_budget(suffix)

    chunks_by_relationship: dict[str, list[str]] = {}
    for child_relationship in child_relationships:
        queryable_fields = relationships_to_fields[child_relationship]
        order_by = _child_order_by(queryable_fields)
        fields = sorted(f for f in queryable_fields if f != ID_FIELD)
        # the subquery wrapper plus "Id, " is overhead a field chunk must leave room for
        wrapper_length = _url_encoded_length(
            _make_child_subquery(child_relationship, [ID_FIELD], order_by)
            + SOQL_FIELD_SEPARATOR
        )
        field_chunks = _pack_for_url(
            fields, SOQL_FIELD_SEPARATOR, budget - wrapper_length
        ) or [[]]
        chunks_by_relationship[child_relationship] = [
            _make_child_subquery(child_relationship, [ID_FIELD, *chunk], order_by)
            for chunk in field_chunks
        ]

    # round k holds chunk k of every relationship, so one query never carries
    # two subqueries on the same relationship (the response keys rows by it)
    queries: list[str] = []
    for round_chunks in zip_longest(*chunks_by_relationship.values()):
        subqueries = [subquery for subquery in round_chunks if subquery is not None]
        queries.extend(
            SOQL_SELECT_PREFIX + SOQL_FIELD_SEPARATOR.join(group) + suffix
            for group in _pack_for_url(
                subqueries, SOQL_FIELD_SEPARATOR, budget, SOQL_MAX_SUBQUERIES
            )
        )
    return queries


@retry_builder(
    tries=5,
    delay=2,
    backoff=2,
    max_delay=60,
    exceptions=(SalesforceRefusedRequest,),
)
@rate_limit_builder(max_calls=50, period=60)
def _object_type_has_api_data(
    sf_client: Salesforce, sf_type: str, time_filter: str
) -> bool:
    """
    Use the rest api to check to make sure the query will result in a non-empty response.
    """
    try:
        # SOQL cannot bind names; validate. time_filter is built internally.
        validate_sf_identifier(sf_type)
        query = f"SELECT Count() FROM {sf_type}{time_filter} LIMIT 1"  # noqa: S608
        result = sf_client.query(query)
        if result["totalSize"] == 0:
            return False
    except SalesforceRefusedRequest as e:
        if is_salesforce_rate_limit_error(e):
            logger.warning(
                "Salesforce rate limit exceeded for object type check: %s", sf_type
            )
            # Add additional delay for rate limit errors
            time.sleep(3)
        raise

    except Exception as e:
        if "OPERATION_TOO_LARGE" not in str(e):
            logger.warning("Object type %s doesn't support query: %s", sf_type, e)
            return False
    return True


def _bulk_retrieve_from_salesforce(
    sf_type: str,
    query: str,
    target_dir: str,
    sf_client: OnyxSalesforce,
) -> tuple[str, list[str] | None]:
    """Returns a tuple of
    1. the salesforce object type (NOTE: seems redundant)
    2. the list of CSV's written into the target directory
    """

    def build_bulk_type() -> SFBulk2Type:
        bulk_2_handler = SFBulk2Handler(
            session_id=sf_client.session_id,
            bulk2_url=sf_client.bulk2_url,
            proxies=sf_client.proxies,
            session=sf_client.session,
        )
        return SFBulk2Type(
            object_name=sf_type,
            bulk2_url=bulk_2_handler.bulk2_url,
            headers=bulk_2_handler.headers,
            session=bulk_2_handler.session,
        )

    def download() -> list[QueryResult]:
        return build_bulk_type().download(
            query=query,
            path=target_dir,
            max_records=500000,
        )

    logger.info("Downloading %s", sf_type)
    logger.debug("Query: %s", query)

    try:
        try:
            results = download()
        except SalesforceExpiredSession:
            # Refresh can rotate persisted credentials; call it only after rejection.
            sf_client.refresh_session()
            results = download()

        all_download_paths: list[str] = []
        for result in results:
            original_file_path = result["file"]
            directory, filename = os.path.split(original_file_path)
            new_filename = f"{sf_type}.{filename}"
            new_file_path = os.path.join(directory, new_filename)
            os.rename(original_file_path, new_file_path)
            all_download_paths.append(new_file_path)
    except Exception as e:
        logger.error(
            "Failed to download salesforce csv for object type %s: %s", sf_type, e
        )
        logger.warning("Exceptioning query for object type %s: %s", sf_type, query)
        return sf_type, None
    finally:
        gc.collect()

    logger.info("Downloaded %s to %s", sf_type, all_download_paths)
    return sf_type, all_download_paths


def fetch_all_csvs_in_parallel(
    sf_client: OnyxSalesforce,
    all_types_to_filter: dict[str, bool],
    queryable_fields_by_type: dict[str, set[str]],
    start: SecondsSinceUnixEpoch | None,
    end: SecondsSinceUnixEpoch | None,
    target_dir: str,
) -> dict[str, list[str] | None]:
    """
    Fetches all the csvs in parallel for the given object types
    Returns a dict of (sf_type, full_download_path)

    NOTE: We can probably lift object type has api data out of here
    """

    type_to_query = {}

    # query the available fields for each object type and determine how to filter
    for sf_type, apply_filter in all_types_to_filter.items():
        queryable_fields = queryable_fields_by_type[sf_type]

        time_filter = ""
        while True:
            if not apply_filter:
                break

            if start is not None and end is not None:
                time_filter_temp = _make_time_filter_for_sf_type(
                    queryable_fields, start, end
                )
                if time_filter_temp is None:
                    logger.warning(
                        "Object type not filterable: type=%s fields=%s",
                        sf_type,
                        queryable_fields,
                    )
                    time_filter = ""
                else:
                    logger.info(
                        "Object type filterable: type=%s filter=%s",
                        sf_type,
                        time_filter_temp,
                    )
                    time_filter = time_filter_temp

            break

        if not _object_type_has_api_data(sf_client, sf_type, time_filter):
            logger.warning("Object type skipped (no data available): type=%s", sf_type)
            continue

        query = _make_time_filtered_query(queryable_fields, sf_type, time_filter)
        type_to_query[sf_type] = query

    logger.info(
        "Object types to query: initial=%s queryable=%s",
        len(all_types_to_filter),
        len(type_to_query),
    )

    # Run the bulk retrieve in parallel
    # limit to 4 to help with memory usage
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(
            lambda object_type: _bulk_retrieve_from_salesforce(
                sf_type=object_type,
                query=type_to_query[object_type],
                target_dir=target_dir,
                sf_client=sf_client,
            ),
            type_to_query.keys(),
        )
        return dict(results)
