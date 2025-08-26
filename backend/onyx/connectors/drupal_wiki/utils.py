from datetime import datetime
from datetime import timezone

from bs4 import BeautifulSoup

from onyx.utils.logger import setup_logger

logger = setup_logger()


def build_drupal_wiki_document_id(base_url: str, page_id: int) -> str:
    """Build a document ID for a Drupal Wiki page using the real URL format"""
    # Ensure base_url ends with a slash
    if not base_url.endswith("/"):
        base_url += "/"
    return f"{base_url}node/{page_id}"


def extract_text_from_html(html_content: str) -> str:
    """Extract text from HTML content"""
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "html.parser")

    for script in soup(["script", "style"]):
        script.extract()

    text = soup.get_text(separator="\n", strip=True)

    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = "\n".join(chunk for chunk in chunks if chunk)

    return text


def datetime_from_timestamp(timestamp: int) -> datetime:
    """Convert a Unix timestamp to a datetime object in UTC"""

    return datetime.fromtimestamp(timestamp, tz=timezone.utc)
