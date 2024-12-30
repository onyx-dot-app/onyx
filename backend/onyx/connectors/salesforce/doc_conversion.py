import re
from collections import OrderedDict

from onyx.connectors.models import Section

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


def _field_value_is_child_object(field_value: dict) -> bool:
    """
    Checks if the field value is a child object.
    """
    return (
        isinstance(field_value, OrderedDict)
        and "records" in field_value.keys()
        and isinstance(field_value["records"], list)
        and len(field_value["records"]) > 0
        and "Id" in field_value["records"][0].keys()
    )


def extract_sections(salesforce_object: dict, base_url: str) -> list[Section]:
    """
    This goes through the salesforce_object and extracts the top level fields as a Section.
    It also goes through the child objects and extracts them as Sections.
    """
    top_level_dict = {}

    child_object_sections = []
    for field_name, field_value in salesforce_object.items():
        # If the field value is not a child object, add it to the top level dict
        # to turn into text for the top level section
        if not _field_value_is_child_object(field_value):
            top_level_dict[field_name] = field_value
            continue

        # If the field value is a child object, extract the child objects and add them as sections
        for record in field_value["records"]:
            child_object_id = record["Id"]
            child_object_sections.append(
                Section(
                    text=f"Child Object(s): {field_name}\n{_extract_dict_text(record)}",
                    link=f"{base_url}/{child_object_id}",
                )
            )

    top_level_id = salesforce_object["Id"]
    top_level_section = Section(
        text=_extract_dict_text(top_level_dict),
        link=f"{base_url}/{top_level_id}",
    )
    return [top_level_section, *child_object_sections]
