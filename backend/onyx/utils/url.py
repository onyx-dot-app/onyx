from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse


def add_url_params(url: str, params: dict) -> str:
    """
    Add parameters to a URL, handling existing parameters properly.

    Args:
        url: The original URL
        params: Dictionary of parameters to add

    Returns:
        URL with added parameters
    """
    # Parse the URL
    parsed_url = urlparse(url)

    # Get existing query parameters
    query_params = parse_qs(parsed_url.query)

    # Update with new parameters
    for key, value in params.items():
        query_params[key] = [value]

    # Build the new query string
    new_query = urlencode(query_params, doseq=True)

    # Reconstruct the URL with the new query string
    new_url = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment,
        )
    )

    return new_url
