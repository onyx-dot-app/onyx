from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class GoogleDriveConnectorConfig(ConnectorConfig):
    include_shared_drives: bool = False
    include_my_drives: bool = False
    include_files_shared_with_me: bool = False
    shared_drive_urls: str | None = None
    my_drive_emails: str | None = None
    shared_folder_urls: str | None = None
    specific_user_emails: str | None = None
    exclude_domain_link_only: bool = False
    batch_size: int = INDEX_BATCH_SIZE
    # Deprecated: kept so stored legacy configs still validate.
    folder_paths: list[str] | None = None
    include_shared: bool | None = None
    follow_shortcuts: bool | None = None
    only_org_public: bool | None = None
    continue_on_failure: bool | None = None
