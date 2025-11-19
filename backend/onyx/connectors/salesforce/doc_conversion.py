import re
from typing import Any
from typing import cast

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.connectors.salesforce.onyx_salesforce import OnyxSalesforce
from onyx.connectors.salesforce.sqlite_functions import OnyxSalesforceSQLite
from onyx.connectors.salesforce.utils import ID_FIELD
from onyx.connectors.salesforce.utils import MODIFIED_FIELD
from onyx.connectors.salesforce.utils import NAME_FIELD
from onyx.connectors.salesforce.utils import SalesforceObject
from onyx.utils.logger import setup_logger

logger = setup_logger()

ID_PREFIX = "SALESFORCE_"

# All of these types of keys are handled by specific fields in the doc
# conversion process (E.g. URLs) or are not useful for the user (E.g. UUIDs)
_SF_JSON_FILTER = r"Id$|Date$|stamp$|url$"


def _clean_salesforce_dict(data: dict | list) -> dict | list:
    """Clean and transform Salesforce API response data by recursively:
    1. Extracting records from the response if present
    2. Merging attributes into the main dictionary
    3. Filtering out keys matching certain patterns (Id, Date, stamp, url)
    4. Removing '__c' suffix from custom field names
    5. Removing None values and empty containers

    Args:
        data: A dictionary or list from Salesforce API response

    Returns:
        Cleaned dictionary or list with transformed keys and filtered values
    """
    if isinstance(data, dict):
        if "records" in data.keys():
            data = data["records"]
    if isinstance(data, dict):
        if "attributes" in data.keys():
            if isinstance(data["attributes"], dict):
                data.update(data.pop("attributes"))

    if isinstance(data, dict):
        filtered_dict = {}
        for key, value in data.items():
            if not re.search(_SF_JSON_FILTER, key, re.IGNORECASE):
                # remove the custom object indicator for display
                if "__c" in key:
                    key = key[:-3]
                if isinstance(value, (dict, list)):
                    filtered_value = _clean_salesforce_dict(value)
                    # Only add non-empty dictionaries or lists
                    if filtered_value:
                        filtered_dict[key] = filtered_value
                elif value is not None:
                    filtered_dict[key] = value
        return filtered_dict

    if isinstance(data, list):
        filtered_list = []
        for item in data:
            filtered_item: dict | list
            if isinstance(item, (dict, list)):
                filtered_item = _clean_salesforce_dict(item)
                # Only add non-empty dictionaries or lists
                if filtered_item:
                    filtered_list.append(filtered_item)
            elif item is not None:
                filtered_list.append(item)
        return filtered_list

    return data


def _json_to_natural_language(data: dict | list, indent: int = 0) -> str:
    """Convert a nested dictionary or list into a human-readable string format.

    Recursively traverses the data structure and formats it with:
    - Key-value pairs on separate lines
    - Nested structures indented for readability
    - Lists and dictionaries handled with appropriate formatting

    Args:
        data: The dictionary or list to convert
        indent: Number of spaces to indent (default: 0)

    Returns:
        A formatted string representation of the data structure
    """
    result = []
    indent_str = " " * indent

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                result.append(f"{indent_str}{key}:")
                result.append(_json_to_natural_language(value, indent + 2))
            else:
                result.append(f"{indent_str}{key}: {value}")
    elif isinstance(data, list):
        for item in data:
            result.append(_json_to_natural_language(item, indent + 2))

    return "\n".join(result)


def _extract_section(salesforce_object_data: dict[str, Any], link: str) -> TextSection:
    """Converts a dict to a TextSection"""

    # Extract text from a Salesforce API response dictionary by:
    # 1. Cleaning the dictionary
    # 2. Converting the cleaned dictionary to natural language
    processed_dict = _clean_salesforce_dict(salesforce_object_data)
    natural_language_for_dict = _json_to_natural_language(processed_dict)

    return TextSection(
        text=natural_language_for_dict,
        link=link,
    )


def _extract_primary_owner(
    sf_db: OnyxSalesforceSQLite,
    sf_object: SalesforceObject,
) -> BasicExpertInfo | None:
    object_dict = sf_object.data
    if not (last_modified_by_id := object_dict.get("LastModifiedById")):
        logger.warning(f"No LastModifiedById found for {sf_object.id}")
        return None
    if not (last_modified_by := sf_db.get_record(last_modified_by_id)):
        logger.warning(f"No LastModifiedBy found for {last_modified_by_id}")
        return None

    user_data = last_modified_by.data
    expert_info = BasicExpertInfo(
        first_name=user_data.get("FirstName"),
        last_name=user_data.get("LastName"),
        email=user_data.get("Email"),
        display_name=user_data.get(NAME_FIELD),
    )

    # Check if all fields are None
    if (
        expert_info.first_name is None
        and expert_info.last_name is None
        and expert_info.email is None
        and expert_info.display_name is None
    ):
        logger.warning(f"No identifying information found for user {user_data}")
        return None

    return expert_info


def convert_sf_query_result_to_doc(
    record_id: str,
    record: dict[str, Any],
    child_records: dict[str, dict[str, Any]],
    primary_owner_list: list[BasicExpertInfo] | None,
    sf_client: OnyxSalesforce,
) -> Document:
    """Generates a yieldable Document from query results"""

    base_url = f"https://{sf_client.sf_instance}"
    extracted_doc_updated_at = time_str_to_utc(record[MODIFIED_FIELD])
    extracted_semantic_identifier = record.get(NAME_FIELD) or record.get(
        ID_FIELD, "Unknown Object"
    )

    sections = [_extract_section(record, f"{base_url}/{record_id}")]
    for child_record_key, child_record in child_records.items():
        if not child_record:
            continue

        key_fields = child_record_key.split(":")
        child_record_id = key_fields[1]

        child_text_section = _extract_section(
            child_record,
            f"{base_url}/{child_record_id}",
        )
        sections.append(child_text_section)

    doc = Document(
        id=f"{ID_PREFIX}{record_id}",
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.SALESFORCE,
        semantic_identifier=extracted_semantic_identifier,
        doc_updated_at=extracted_doc_updated_at,
        primary_owners=primary_owner_list,
        metadata={},
    )
    return doc


def convert_sf_object_to_doc(
    sf_db: OnyxSalesforceSQLite,
    sf_object: SalesforceObject,
    sf_instance: str,
) -> Document:
    """Would be nice if this function was documented"""
    object_dict = sf_object.data
    salesforce_id = object_dict[ID_FIELD]
    onyx_salesforce_id = f"{ID_PREFIX}{salesforce_id}"
    base_url = f"https://{sf_instance}"
    extracted_doc_updated_at = time_str_to_utc(object_dict[MODIFIED_FIELD])
    extracted_semantic_identifier = object_dict.get(NAME_FIELD) or object_dict.get(
        ID_FIELD, "Unknown Object"
    )

    sections = [_extract_section(sf_object.data, f"{base_url}/{sf_object.id}")]
    for id in sf_db.get_child_ids(sf_object.id):
        if not (child_object := sf_db.get_record(id, isChild=True)):
            continue
        sections.append(
            _extract_section(child_object.data, f"{base_url}/{child_object.id}")
        )

    # NOTE(rkuo): does using the parent last modified make sense if the update
    # is being triggered because a child object changed?
    primary_owner_list: list[BasicExpertInfo] | None = None

    primary_owner = sf_db.make_basic_expert_info_from_record(sf_object)
    if primary_owner:
        primary_owner_list = [primary_owner]

    doc = Document(
        id=onyx_salesforce_id,
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.SALESFORCE,
        semantic_identifier=extracted_semantic_identifier,
        doc_updated_at=extracted_doc_updated_at,
        primary_owners=primary_owner_list,
        metadata={},
    )
    return doc
