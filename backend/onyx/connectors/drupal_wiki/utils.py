from onyx.utils.logger import setup_logger

logger = setup_logger()


def build_drupal_wiki_document_id(base_url: str, page_id: int) -> str:
    """Build a document ID for a Drupal Wiki page using the real URL format"""
    # Ensure base_url ends with a slash
    base_url = base_url.rstrip("/") + "/"
    return f"{base_url}node/{page_id}"
