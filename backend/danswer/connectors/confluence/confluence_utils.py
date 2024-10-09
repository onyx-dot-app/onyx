import bs4


def build_confluence_document_id(base_url: str, content_url: str) -> str:
    """For confluence, the document id is the page url for a page based document
        or the attachment download url for an attachment based document

    Args:
        base_url (str): The base url of the Confluence instance
        content_url (str): The url of the page or attachment download url

    Returns:
        str: The document id
    """
    return f"{base_url}{content_url}"


def get_used_attachments(text: str) -> list[str]:
    """Parse a Confluence html page to generate a list of current
        attachment in used

    Args:
        text (str): The page content

    Returns:
        list[str]: List of filenames currently in use by the page text
    """
    files_in_used = []
    soup = bs4.BeautifulSoup(text, "html.parser")
    for attachment in soup.findAll("ri:attachment"):
        files_in_used.append(attachment.attrs["ri:filename"])
    return files_in_used
