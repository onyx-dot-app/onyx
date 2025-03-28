import re
from typing import Union

from bs4 import BeautifulSoup


SF_JSON_FILTER = r"Id$|Date$|stamp$|url$"


def _clean_salesforce_dict(data: Union[dict, list]) -> Union[dict, list]:
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
            if not re.search(SF_JSON_FILTER, key, re.IGNORECASE):
                if "__c" in key:  # remove the custom object indicator for display
                    key = key[:-3]
                if isinstance(value, (dict, list)):
                    filtered_value = _clean_salesforce_dict(value)
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
                if filtered_item:
                    filtered_list.append(filtered_item)
            elif item is not None:
                filtered_list.append(filtered_item)
        return filtered_list
    else:
        return data


def _json_to_natural_language(data: Union[dict, list], indent: int = 0) -> str:
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
            result.append(_json_to_natural_language(item, indent))
    else:
        result.append(f"{indent_str}{data}")

    return "\n".join(result)


def extract_dict_text(raw_dict: dict) -> str:
    processed_dict = _clean_salesforce_dict(raw_dict)

    if "Resolution" in processed_dict:
        processed_dict["Resolution"] = clean_html(processed_dict["Resolution"])

    natural_language_dict = _json_to_natural_language(processed_dict)
    return natural_language_dict


def clean_html(html_content: str) -> str:
    """
    Cleans the HTML content by removing tags and returning the plain text,
    while preserving the links.
    :param html_content: HTML content as string
    :return: Cleaned text with preserved links
    """
    soup = BeautifulSoup(html_content, "lxml")

    # Replace <a> tags with their text and the href as a link in brackets
    for a_tag in soup.find_all("a", href=True):
        a_tag.insert_before(f"[{a_tag.get_text()}]({a_tag['href']})")
        a_tag.decompose()

    cleaned_text = soup.get_text(separator="\n", strip=True)

    # Replace non-breaking spaces (\xa0) with regular spaces
    cleaned_text = cleaned_text.replace("\xa0", " ")

    return cleaned_text
