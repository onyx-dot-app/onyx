from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE

DEFAULT_JSM_PAGE_LIMIT = 50
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30


class JiraServiceManagementConnectorConfig(BaseModel):
    jira_base_url: str
    project_key: str | None = None
    service_desk_ids: list[str] | None = None
    request_types: list[str] | None = None
    include_internal_comments: bool = False
    include_sla_metrics: bool = True
    include_attachments: bool = False
    jql_query: str | None = None
    scoped_token: bool = False
    batch_size: int = INDEX_BATCH_SIZE
    page_limit: int = DEFAULT_JSM_PAGE_LIMIT
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS
