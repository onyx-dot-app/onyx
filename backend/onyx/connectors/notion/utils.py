"""Utility functions for Notion connector."""

from typing import Any

from onyx.utils.logger import setup_logger

logger = setup_logger()


def properties_to_str(properties: dict[str, Any]) -> str:
    """Convert Notion properties to a string representation.

    Recursively processes Notion property structures to extract readable text values.
    Handles nested properties, lists, dates, and various property types.

    Args:
        properties: Dictionary of Notion properties

    Returns:
        Formatted string representation of properties
    """

    def _recurse_list_properties(inner_list: list[Any]) -> str | None:
        list_properties: list[str | None] = []
        for item in inner_list:
            if item and isinstance(item, dict):
                list_properties.append(_recurse_properties(item))
            elif item and isinstance(item, list):
                list_properties.append(_recurse_list_properties(item))
            else:
                list_properties.append(str(item))
        return (
            ", ".join(
                [list_property for list_property in list_properties if list_property]
            )
            or None
        )

    def _recurse_properties(inner_dict: dict[str, Any]) -> str | None:
        sub_inner_dict: dict[str, Any] | list[Any] | str = inner_dict
        while isinstance(sub_inner_dict, dict) and "type" in sub_inner_dict:
            type_name = sub_inner_dict["type"]
            sub_inner_dict = sub_inner_dict[type_name]

            # If the innermost layer is None, the value is not set
            if not sub_inner_dict:
                return None

        # TODO there may be more types to handle here
        if isinstance(sub_inner_dict, list):
            return _recurse_list_properties(sub_inner_dict)
        elif isinstance(sub_inner_dict, str):
            # For some objects the innermost value could just be a string
            return sub_inner_dict
        elif isinstance(sub_inner_dict, dict):
            if "name" in sub_inner_dict:
                return sub_inner_dict["name"]
            if "content" in sub_inner_dict:
                return sub_inner_dict["content"]
            start = sub_inner_dict.get("start")
            end = sub_inner_dict.get("end")
            if start is not None:
                if end is not None:
                    return f"{start} - {end}"
                return start
            elif end is not None:
                return f"Until {end}"

            if "id" in sub_inner_dict:
                # This is not useful to index, it's a reference to another Notion object
                # and this ID value in plaintext is useless outside of the Notion context
                logger.debug("Skipping Notion object id field property")
                return None

        logger.debug(f"Unreadable property from innermost prop: {sub_inner_dict}")
        return None

    result = ""
    for prop_name, prop in properties.items():
        if not prop or not isinstance(prop, dict):
            continue

        try:
            inner_value = _recurse_properties(prop)
        except Exception as e:
            # This is not a critical failure, these properties are not the actual contents of the page
            # more similar to metadata
            logger.warning(f"Error recursing properties for {prop_name}: {e}")
            continue
        # Not a perfect way to format Notion database tables but there's no perfect representation
        # since this must be represented as plaintext
        if inner_value:
            result += f"{prop_name}: {inner_value}\t"

    return result


def extract_page_title(
    page_properties: dict[str, Any], database_name: str | None = None
) -> str | None:
    """Extract the title from a Notion page.

    Args:
        page_properties: Dictionary of page properties
        database_name: Optional database name (for database-type pages)

    Returns:
        Page title string or None if not found
    """
    if database_name:
        return database_name
    for prop in page_properties.values():
        if prop.get("type") == "title" and prop.get("title"):
            return " ".join([t.get("plain_text", "") for t in prop["title"]]).strip()
    return None


def build_page_metadata(
    page_id: str,
    page_url: str,
    created_time: str,
    last_edited_time: str,
    archived: bool,
    properties: dict[str, Any],
) -> dict[str, str | list[str]]:
    """Build document metadata from page information.

    Args:
        page_id: Notion page ID
        page_url: Notion page URL
        created_time: Page creation timestamp
        last_edited_time: Page last edited timestamp
        archived: Whether page is archived
        properties: Page properties dictionary

    Returns:
        Metadata dictionary with string/list values (as required by Document model)
    """
    metadata: dict[str, str | list[str]] = {
        "notion_page_id": page_id,
        "notion_page_url": page_url,
        "created_time": created_time,
        "last_edited_time": last_edited_time,
        "archived": str(archived).lower(),
    }

    # Add formatted property values to metadata for searchability
    if properties:
        for prop_name, prop in properties.items():
            if prop and isinstance(prop, dict):
                prop_value = properties_to_str({prop_name: prop})
                if prop_value:
                    # Store property value in metadata (remove the "prop_name: " prefix)
                    prop_value_clean = prop_value.replace(f"{prop_name}: ", "").strip()
                    if prop_value_clean:
                        metadata[f"property_{prop_name}"] = prop_value_clean

    return metadata
