from onyx.connectors.connector_config import ConnectorConfig


class GithubConnectorConfig(ConnectorConfig):
    repo_owner: str
    repositories: str | None = None
    state_filter: str = "all"
    include_prs: bool = True
    include_issues: bool = False
    include_files: bool = False
    branch: str | None = None
