import re
from typing import cast

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.connectors.salesforce.sqlite_functions import OnyxSalesforceSQLite
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
    elif isinstance(data, list):
        filtered_list = []
        for item in data:
            filtered_item: dict | list
            if isinstance(item, (dict, list)):
                filtered_item = _clean_salesforce_dict(item)
                # Only add non-empty dictionaries or lists
                if filtered_item:
                    filtered_list.append(filtered_item)
            elif item is not None:
                filtered_list.append(filtered_item)
        return filtered_list
    else:
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


def _extract_dict_text(raw_dict: dict) -> str:
    """Extract text from a Salesforce API response dictionary by:
    1. Cleaning the dictionary
    2. Converting the cleaned dictionary to natural language
    """
    processed_dict = _clean_salesforce_dict(raw_dict)
    natural_language_for_dict = _json_to_natural_language(processed_dict)
    return natural_language_for_dict


def _extract_section(salesforce_object: SalesforceObject, base_url: str) -> TextSection:
    return TextSection(
        text=_extract_dict_text(salesforce_object.data),
        link=f"{base_url}/{salesforce_object.id}",
    )


def _extract_primary_owners(
    sf_db: OnyxSalesforceSQLite,
    sf_object: SalesforceObject,
) -> list[BasicExpertInfo] | None:
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
        display_name=user_data.get("Name"),
    )

    # Check if all fields are None
    if all(
        value is None
        for value in [
            expert_info.first_name,
            expert_info.last_name,
            expert_info.email,
            expert_info.display_name,
        ]
    ):
        logger.warning(f"No identifying information found for user {user_data}")
        return None

    return [expert_info]


def convert_sf_object_to_doc(
    sf_db: OnyxSalesforceSQLite,
    sf_object: SalesforceObject,
    sf_instance: str,
) -> Document:
    object_dict = sf_object.data
    salesforce_id = object_dict["Id"]
    onyx_salesforce_id = f"{ID_PREFIX}{salesforce_id}"
    base_url = f"https://{sf_instance}"
    extracted_doc_updated_at = time_str_to_utc(object_dict["LastModifiedDate"])
    extracted_semantic_identifier = object_dict.get("Name", "Unknown Object")

    sections = [_extract_section(sf_object, base_url)]
    for id in sf_db.get_child_ids(sf_object.id):
        if not (child_object := sf_db.get_record(id)):
            continue
        sections.append(_extract_section(child_object, base_url))

    doc = Document(
        id=onyx_salesforce_id,
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.SALESFORCE,
        semantic_identifier=extracted_semantic_identifier,
        doc_updated_at=extracted_doc_updated_at,
        primary_owners=_extract_primary_owners(sf_db, sf_object),
        metadata={},
    )
    return doc
