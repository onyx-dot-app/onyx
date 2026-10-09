from typing import Any
from urllib.parse import urlparse

from onyx.configs.app_configs import (
    CONFLUENCE_CONNECTOR_LABELS_TO_SKIP,
    CONFLUENCE_TIMEZONE_OFFSET,
    CONTINUE_ON_CONNECTOR_FAILURE,
    INDEX_BATCH_SIZE,
)
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.exceptions import ConnectorValidationError

# Set by the Confluence Cloud OAuth finalize step to the site the user authorized.
_OAUTH_WIKI_BASE_KEY = "wiki_base"


def _site(url: str) -> tuple[str, str]:
    """The URL's scheme and host. The scheme counts: an http URL for an
    https-authorized site would send the token unencrypted."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.scheme.lower(), parsed.netloc.lower()


class ConfluenceCredentialBinding(CredentialBinding):
    wiki_base: str
    is_cloud: bool
    scoped_token: bool = False

    def validate_credential(self, credential_json: dict[str, Any]) -> None:
        authorized_wiki_base = credential_json.get(_OAUTH_WIKI_BASE_KEY)
        if not authorized_wiki_base:
            return
        if _site(self.wiki_base) != _site(authorized_wiki_base):
            raise ConnectorValidationError(
                f"The site URL {self.wiki_base} is not the Confluence site this "
                f"account was authorized for ({authorized_wiki_base})."
            )


class ConfluenceConnectorConfig(ConfluenceCredentialBinding, ConnectorConfig):
    space: str = ""
    page_id: str = ""
    index_recursively: bool = False
    cql_query: str | None = None
    batch_size: int = INDEX_BATCH_SIZE
    continue_on_failure: bool = CONTINUE_ON_CONNECTOR_FAILURE
    labels_to_skip: list[str] = CONFLUENCE_CONNECTOR_LABELS_TO_SKIP
    timezone_offset: float = CONFLUENCE_TIMEZONE_OFFSET
    include_attachments: bool = True
