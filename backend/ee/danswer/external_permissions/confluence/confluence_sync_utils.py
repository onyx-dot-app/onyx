from typing import Any

from atlassian import Confluence  # type:ignore


def build_confluence_client(
    connector_specific_config: dict[str, Any], raw_credentials_json: dict[str, Any]
) -> Confluence:
    is_cloud = connector_specific_config.get("is_cloud", False)
    return Confluence(
        api_version="cloud" if is_cloud else "latest",
        # Remove trailing slash from wiki_base if present
        url=connector_specific_config["wiki_base"].rstrip("/"),
        # passing in username causes issues for Confluence data center
        username=raw_credentials_json["confluence_username"] if is_cloud else None,
        password=raw_credentials_json["confluence_access_token"] if is_cloud else None,
        token=raw_credentials_json["confluence_access_token"] if not is_cloud else None,
    )
